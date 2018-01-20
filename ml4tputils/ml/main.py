import argparse
import os.path as op
import pickle
import torch

from recon.recon import Recon
from ml.tacst_prep import Dataset, PosEvalPt

from ml.poseval.fold_model import PosEvalModel
from ml.poseval.fold_train import PosEvalTrainer #, PosEvalInfer

"""
[Note]

Top-level entry-point for machine learning.
"""


class Preprocess(object):
    def __init__(self, files):
        self.recon = Recon(f_token=False)
        self._preprocess_embed_all(files)

    def _preprocess_embed_all(self, files):
        for file in files:
            self._preprocess_embed_file(file)

    def _preprocess_embed_file(self, file):
        self.recon.recon_file(file, f_verbose=True)

    def get_tactrees(self):
        return self.recon.tactrs


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument("-l", "--load", default="tactr.pickle",
                           type=str, help="Pickle file to load")
    argparser.add_argument("-p", "--poseval", default="poseval.pickle",
                           type=str, help="Pickle file to save to")
    argparser.add_argument("-f", "--fold", action = 'store_true', help="To fold or not to fold")
    argparser.add_argument("--ln", action = 'store_true', help="To norm or not to norm")
    argparser.add_argument("--treelstm", action = 'store_true', help="To tree or not to tree")
    argparser.add_argument("--lstm", action = 'store_true', help="To tree or not to tree")

    argparser.add_argument("--orig", action = 'store_true', help="Old is gold")
    argparser.add_argument('--no-cuda', action='store_true', default=False,
                        help='disables CUDA training')
    argparser.add_argument('--nbatch', type = int, default = 32, help = 'minibatch size')
    argparser.add_argument('--valbatch', type = int, default = 32, help = 'minibatch size for validation')

    argparser.add_argument('--lr', type = float, default=0.001, help = 'learning rate')
    argparser.add_argument('--name', type = str, default = "", help = 'name of experiment')
    argparser.add_argument('--mload', type = str, default = "", help = 'path to load saved model from')


    args = argparser.parse_args()
    assert not (args.lstm and args.treelstm)
    args.cuda = not args.no_cuda and torch.cuda.is_available()

    torch.manual_seed(0)
    if args.cuda:
        torch.cuda.manual_seed(0)

    print(args)
    print("Loading tactrs ...")
    with open(args.load, 'rb') as f:
        tactrs = pickle.load(f)

    print("Loading poseval dataset ...")
    with open(args.poseval, 'rb') as f:
        poseval_dataset, tokens_to_idx = pickle.load(f)

    print("Points Train={} Val={} Test={}".format(len(poseval_dataset.train), len(poseval_dataset.val), len(poseval_dataset.test)))
    if not args.orig:
        model = PosEvalModel(*tokens_to_idx, ln=args.ln, treelstm=args.treelstm, lstm=args.lstm)
        trainer = PosEvalTrainer(model, tactrs, poseval_dataset, args)
        trainer.train()
    else:
        from ml.embed import MyModel, PosEvalTrainer
        print("Original")
        model = MyModel(*tokens_to_idx)
        trainer = PosEvalTrainer(model, tactrs, poseval_dataset.train)
        trainer.train()

    # # Inference
    # model_infer = PosEvalModel(*tokens_to_idx)
    # model_infer.load_state_dict(torch.load(filename))
    # infer = PosEvalInfer(tactrs, model_infer)
    # infer.infer(poseval_dataset)


    # TODO(deh): Uncomment me to test with checker
    # model = PosEvalModel(*tokens_to_idx)
    # trainer1 = PosEvalTrainer(model, tactrs, poseval_dataset,
    #                           "mllogs/embedv1.0.jsonl", f_fold=False)
    # trainer2 = PosEvalTrainer(model, tactrs, poseval_dataset,
    #                           "mllogs/embedv2.0.jsonl", f_fold=True)
    # checker = ChkPosEvalTrainer(trainer1, trainer2)
    # checker.check()
    # trainer1.finalize() 
    # trainer2.finalize()
