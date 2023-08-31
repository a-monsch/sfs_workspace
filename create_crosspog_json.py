import correctionlib._core as core
import correctionlib.schemav2 as schema
import correctionlib.JSONEncoder as JSONEncoder
from workspace_reader import WorkspaceReader
import ROOT
import json
import os
import yaml

# set epsilon value to avoid giant scale factors
epsilon = 0.0001


class CorrectionSet(object):
    def __init__(self, name):
        self.name = name
        self.corrections = []

    def add_correction_file(self, correction_file):
        with open(correction_file) as file:
            data = json.load(file)
            corr = schema.Correction.parse_obj(data)
            self.add_correction(corr)

    def add_correction(self, correction):
        if isinstance(correction, dict):
            self.corrections.append(correction)
        elif isinstance(correction, Correction):
            self.corrections.append(correction.correctionset)
        else:
            raise TypeError(
                "Correction must be a Correction object or a dictionary, not {}".format(
                    type(correction)
                )
            )

    def write_json(self, outputfile):
        # Create the JSON object
        cset = schema.CorrectionSet(
            schema_version=schema.VERSION, corrections=self.corrections
        )
        print(f">>> Writing {outputfile}...")
        JSONEncoder.write(cset, outputfile)
        JSONEncoder.write(cset, outputfile + ".gz")


class Correction(object):
    def __init__(
        self,
        tag,
        name,
        outdir,
        configfile,
        era,
        fname="",
        data_only=False,
        verbose=False,
    ):
        self.tag = tag
        self.name = name
        self.outdir = outdir
        self.configfile = configfile
        self.ptbinning = []
        self.etabinning = []
        self.inputfiles = []
        self.correction = None
        self.era = era
        self.header = ""
        self.fname = fname
        self.info = ""
        self.verbose = verbose
        self.data_only = data_only
        self.correctionset = None
        self.inputobjects = {}
        self.types = ["Data", "Embedding", "DY"]

    def __repr__(self) -> str:
        return "Correction({})".format(self.name)

    def __str__(self) -> str:
        return "Correction({})".format(self.name)

    def parse_config(self):
        pass

    def setup_scheme(self):
        pass

    def generate_sfs(self):
        pass

    def generate_scheme(self):
        pass


class pt_eta_correction(Correction):
    def __init__(
        self,
        tag,
        name,
        configfile,
        era,
        outdir,
        fname="",
        data_only=False,
        verbose=False,
    ):
        super(pt_eta_correction, self).__init__(
            tag,
            name,
            outdir,
            configfile,
            era,
            fname,
            data_only,
            verbose,
        )
        if self.data_only:
            self.types = ["Data"]

    
    def set_workspace(self):
        self.workspace = WorkspaceReader("/work/olavoryk/corr_lib_com/htt_scalefactors_UL_"+str(self.era).replace("UL","")+".root")



    def parse_config(self):
        config = yaml.safe_load(open(self.configfile))
        self.ptbinning = config[self.name]["bins_x"]
        self.etabinning = config[self.name]["bins_y"]
        basename = str(os.path.basename(self.configfile)).split("_")[1]
        self.info = config[self.name]["info"]
        self.header = config[self.name]["header"]


    def GetFromTFile(self, inputfile, object):
        print("Getting ", object, "from ", inputfile)
        f = ROOT.TFile(inputfile)
        obj = f.Get(object).Clone()
        f.Close()
        return obj

    def setup_scheme(self):
        self.correctionset = {
            "version": 0,
            "name": self.name,
            "description": self.info,
            "inputs": [
                {
                    "name": "pt",
                    "type": "real",
                    "description": "Reconstructed muon pT",
                },
                {
                    "name": "abs(eta)",
                    "type": "real",
                    "description": "Reconstructed muon eta",
                },
            ],
            "output": {
                "name": "sf",
                "type": "real",
                "description": "pT-eta-dependent scale factor",
            },
            "data": None,
        }
        if not self.data_only:
            self.correctionset["inputs"].append(
                {
                    "name": "type",
                    "type": "string",
                    "description": "Type of correction: Embedding or MC",
                }
            )

    def generate_sfs(self):
        sfs = {}
        if self.data_only:
            sfs = {
                "nodetype": "binning",
                "input": "pt",
                "edges": self.ptbinning,
                "flow": "clamp",
                "content": [
                    {
                        "nodetype": "binning",
                        "input": "abs(eta)",
                        "edges": self.etabinning,
                        "flow": "clamp",
                        # "content": self.get_sfs_for_etas(
                        #     pt, self.etabinning, self.data_only
                        # ),
                        "content": [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1], 
                    }
                    for pt in self.ptbinning[:-1]
                ],
            }
        else:
            # without data only, we add both the mc and the embedding sfs
            sfs = {
                "nodetype": "binning",
                "input": "pt",
                "edges": self.ptbinning,
                "flow": "clamp",
                "content": [
                    {
                        "nodetype": "binning",
                        "input": "abs(eta)",
                        "edges": self.etabinning,
                        "flow": "clamp",
                        "content": [
                            {
                                "nodetype": "category",
                                "input": "type",
                                "content": [
                                    {
                                        "key": "mc",
                                        # "value": 0.777,                    #it writes mc sf
                                        "value": self.workspace.get_sfs(pt, eta, self.name ,"mc")
                                    },
                                    {
                                        "key": "emb",
                                        "value": self.workspace.get_sfs(pt, eta, self.name ,"emb"),                    #it writes emb sf
                                    },
                                ],
                            }
                            for eta in self.etabinning[:-1]
                        ],
                    }
                    for pt in self.ptbinning[:-1]
                ],
            }
        return schema.Binning.parse_obj(sfs)

 

    def generate_scheme(self):
        self.parse_config()
        self.setup_scheme()
        self.set_workspace()
        self.correctionset["data"] = self.generate_sfs()
        output_corr = schema.Correction.parse_obj(self.correctionset)
        self.correction = output_corr
        # print(JSONEncoder.dumps(self.correction))

    def write_scheme(self):
        if self.verbose >= 2:
            print(JSONEncoder.dumps(self.correction))
        elif self.verbose >= 1:
            print(self.correction)
        if self.fname:
            print(f">>> Writing {self.fname}...")
        JSONEncoder.write(self.correction, self.fname)


# class emb_doublemuon_correction(Correction):
#     def __init__(
#         self,
#         tag,
#         name,
#         configfile,
#         era,
#         outdir,
#         triggernames,
#         fname="",
#         data_only=True,
#         verbose=False,
#     ):
#         super(emb_doublemuon_correction, self).__init__(
#             tag,
#             name,
#             outdir,
#             configfile,
#             era,
#             fname,
#             data_only,
#             verbose,
#         )
#         self.types = ["Data"]
#         self.names = triggernames

#     def parse_config(self):
#         config = yaml.safe_load(open(self.configfile))
#         # self.ptbinning = config[self.name]["bins_x"]
#         # self.etabinning = config[self.name]["bins_y"]


#         self.ptbinning = [10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 31, 34, 37, 40, 45, 50, 60, 70, 100, 1000]   # you should read binning from config file
#         self.etabinning = [0, 0.1, 0.3, 0.8, 1.0, 1.2, 1.6, 1.8, 2.1, 2.4]                                # analogous to pt binning

#         basename = (
#             str(os.path.basename(self.configfile)).split("_")[1].replace(".yaml", "")
#         )

#         self.info = config[self.name]["info"]
#         self.header = config[self.name]["header"]

#         print("\n info: ", self.info)
#         print("header: ", self.header)


#     def setup_scheme(self):
#         self.correctionset = {
#             "version": 0,
#             "name": self.name,
#             "description": self.info,
#             "inputs": [
#                 {
#                     "name": "pt_1",
#                     "type": "real",
#                     "description": "Reconstructed leading genparticle pT",
#                 },
#                 {
#                     "name": "abs(eta_1)",
#                     "type": "real",
#                     "description": "Reconstructed leading genparticle eta",
#                 },
#                 {
#                     "name": "pt_2",
#                     "type": "real",
#                     "description": "Reconstructed trailing genparticle pT",
#                 },
#                 {
#                     "name": "abs(eta_2)",
#                     "type": "real",
#                     "description": "Reconstructed trailing genparticle eta",
#                 },
#             ],
#             "output": {
#                 "name": "sf",
#                 "type": "real",
#                 "description": "pT-eta-dependent scale factor",
#             },
#             "data": None,
#         }
#         if not self.data_only:
#             self.correctionset["inputs"].append(
#                 {
#                     "name": "type",
#                     "type": "string",
#                     "description": "Type of correction: Embedding or MC",
#                 }
#             )

#     def generate_sfs(self):
#         if self.data_only:
#             sfs = schema.Binning.parse_obj(
#                 {
#                     "nodetype": "binning",
#                     "input": "pt_1",
#                     "edges": self.ptbinning,
#                     "flow": "clamp",
#                     "content": [
#                         {
#                             "nodetype": "binning",
#                             "input": "abs(eta_1)",
#                             "edges": self.etabinning,
#                             "flow": "clamp",
#                             "content": [
#                                 {
#                                     "nodetype": "binning",
#                                     "input": "pt_2",
#                                     "edges": self.ptbinning,
#                                     "flow": "clamp",
#                                     "content": [
#                                         {
#                                             "nodetype": "binning",
#                                             "input": "abs(eta_2)",
#                                             "edges": self.etabinning,
#                                             "flow": "clamp",
#                                             # "content": self.get_sf(
#                                             #     pt_1,
#                                             #     eta_1,
#                                             #     pt_2,
#                                             #     self.etabinning,
#                                             #     self.data_only,
#                                             # ),
#                                             "content": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9 ],
#                                         }
#                                         for pt_2 in self.ptbinning[:-1]
#                                     ],
#                                 }
#                                 for eta_1 in self.etabinning[:-1]
#                             ],
#                         }
#                         for pt_1 in self.ptbinning[:-1]
#                     ],
#                 }
#             )
#         else:
#             raise Exception("Not implemented")
#         return sfs

#     def get_sf(self, pt_1, eta_1, pt_2, eta_binning, data_only, inputtype=None):
#         sfs = []
#         # leave of the last eta bin, which is the overflow bin
#         for eta_2 in eta_binning[:-1]:
#             efficiency = {}
#             for lepton in [1, 2]:
#                 for trigger in self.names:
#                     shortname = "17" if "17" in trigger else "8"
#                     if lepton == 1:
#                         pt_ = pt_1
#                         eta_ = eta_1
#                     else:
#                         pt_ = pt_2
#                         eta_ = eta_2
#                     efficiency["{}_{}".format(shortname, lepton)] = self.inputobjects[
#                         trigger
#                     ]["object"].GetBinContent(
#                         self.inputobjects[trigger]["object"].GetXaxis().FindBin(pt_),
#                         self.inputobjects[trigger]["object"].GetYaxis().FindBin(eta_),
#                     )
#             sf = 1.0 / (
#                 efficiency["8_1"] * efficiency["17_2"]
#                 + efficiency["8_2"] * efficiency["17_1"]
#                 - efficiency["17_1"] * efficiency["17_2"]
#             )
#             # sanitize if all efficiencies are close to zero
#             if (
#                 abs(
#                     efficiency["8_1"] * efficiency["17_2"]
#                     + efficiency["8_2"] * efficiency["17_1"]
#                     - efficiency["17_1"] * efficiency["17_2"]
#                 )
#                 < epsilon
#             ):
#                 print(
#                     "Sanitizing SF for pt_1 = {}, eta_1 = {}, pt_2 = {}, eta_2 = {}".format(
#                         pt_1, eta_1, pt_2, eta_2
#                     )
#                 )
#                 print("calefactor before: {}".format(sf))
#                 print("Scalefactor after: ", 1.0)
#                 sf = 0.0
#             sfs.append(sf)
#             if self.verbose:
#                 print("pt_1:", pt_1, "eta_1:", eta_1, "pt_2:", pt_2, "eta_2:", eta_2)
#                 print("sf:", sf)
#         return sfs

#     def generate_scheme(self):
#         self.parse_config()
#         self.setup_scheme()
#         self.correctionset["data"] = self.generate_sfs()
#         output_corr = schema.Correction.parse_obj(self.correctionset)
#         self.correction = output_corr

#     def write_scheme(self):
#         if self.verbose >= 2:
#             print(JSONEncoder.dumps(self.correction))
#         elif self.verbose >= 1:
#             print(self.correction)
#         if self.fname:
#             print(f">>> Writing {self.fname}...")
#         JSONEncoder.write(self.correction, self.fname)


if __name__ == "__main__":

    ROOT.PyConfig.IgnoreCommandLineOptions = True
    ROOT.gROOT.SetBatch(ROOT.kTRUE)
    # for keeping the histograms in memory
    ROOT.TH1.AddDirectory(0)
    test = pt_eta_correction(
        tag="test",
        name="EmbID_pt_eta_bins",
        outdir="output/jsons",
        configfile="settings/settings_embeddingselection_2018UL.yaml",
        era="2018UL",
        fname="{}/{}.json".format("output/jsons", "test"),
        data_only=True,
        verbose=False,
    )
    test.generate_scheme()
