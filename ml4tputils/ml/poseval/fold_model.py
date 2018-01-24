import gc
import os
import psutil
import sys
from time import time

import torch
import torch.autograd as autograd
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import numpy as np

from coq.ast import *
from coq.decode import DecodeCoqExp
from lib.myenv import FastEnv
from lib.myutil import NotFound

from coq.util import SizeCoqExp

from ml.utils import ResultLogger

import ml.torchfold as ptf


"""
[Note]

Version that uses torchfold
1. Embed Coq tactic trees into R^D vectors
2. Model uses embeddings to obtain prediction of:
    close, medium, far
"""

# -------------------------------------------------
# Helper

def seq_embed(name, folder, xs, init, ln, tup, input_dropout):
    # Preprocess for fold
    if tup:
        hidden = folder.add('tup_identity', *init).split(2)
        for i, x in enumerate(xs):
            if not isinstance(x, (tuple, list, nn.ParameterList)):
                xs[i] = x.split(2)
    else:
        hidden = folder.add('identity', init)

    # Input dropout
    if input_dropout:
        if tup:
            hidden = folder.add('input_dropout_f', hidden[0]), hidden[1]
            for i,x in enumerate(xs):
                xs[i] = folder.add('input_dropout_f', x[0]), x[1]
        else:
            hidden = folder.add('input_dropout_f', hidden)
            for i,x in enumerate(xs):
                xs[i] = folder.add('input_dropout_f', x)

    # Cell sequence
    for i,x in enumerate(xs):
        if tup:
            hidden = folder.add(name + '_cell_f', *x, *hidden).split(2)
            assert isinstance(hidden, (tuple, list))
        else:
            hidden = folder.add(name + '_cell_f', x, hidden)

    # Weird layer-norm
    if ln:
        if tup:
            hidden = folder.add(name[:3] + '_ln_f', hidden[0]), hidden[1]
        else:
            hidden = folder.add(name[:3] + '_ln_f', hidden)
    return hidden

def seq_sigmoid_attn_embed(folder, xs, sv_init, ln, tup, input_dropout):
    if input_dropout:
        if tup:
            for i, x in enumerate(xs):
                xs[i] = folder.add('input_dropout_f', x[0]), x[1]
        else:
            for i, x in enumerate(xs):
                xs[i] = folder.add('input_dropout_f', x)

    # Attention
    conclu = xs[0]
    other = xs[1:]
    q = folder.add('attn_q_f', conclu)
    sv = folder.add('attn_identity', sv_init)
    for x in other:
        sv = folder.add('attn_sv_f', q, x, sv)

    return sv



# def ast_embed(folder, xs, init, ln):
#     hidden = init
#     for i, x in enumerate(xs):
#         #print("GRU Embed ",i, x.shape)
#         hidden = folder.add('ast_cell_f', x, hidden) #cell(x.view(1, -1, 128), hidden)
#     #print("hidden shape", hidden.shape)
#     if ln:
#         #print("using ln")
#         hidden = folder.add('ast_ln_f', hidden)
#     return hidden
#
# def ctx_embed(folder, xs, init, ln):
#     hidden = folder.add('ctx_identity', init)
#     for i, x in enumerate(xs):
#         #print("GRU Embed ",i, x.shape)
#         hidden = folder.add('ctx_cell_f', x, hidden) #cell(x.view(1, -1, 128), hidden)
#     #print("hidden shape", hidden.shape)
#     if ln:
#         # Weird version of Layernorm
#         #print("using ln")
#         hidden = folder.add('ctx_ln_f', hidden)
#     return hidden

# -------------------------------------------------
# Fold over anything
class Folder(object):
    def __init__(self, model, foldy, cuda):
        # Folding state
        self.model = model
        self.foldy = foldy
        self.cuda = cuda
        self.max_batch_ops = {}
        if not self.cuda:
            # Optimisation for CPU. Ad-hoc, so might not be optimal

            # Embed lookups
            self.max_batch_ops['embed_lookup_f'] = 128

            # Cell calls
            for name in ["", "lstm", "tree"]:
                self.max_batch_ops['ast_' + name + '_cell_f'] = 32
                self.max_batch_ops['ctx_' + name + '_cell_f'] = 32

            # FC calls
            self.max_batch_ops['proj_f'] = 32
            self.max_batch_ops['final_f'] = 32
        self.reset()

    def reset(self):
        """Reset folding state"""
        if self.foldy:
            #print("Folding")
            self._folder = ptf.Fold(max_batch_ops = self.max_batch_ops)
        else:
            #print("Not folding")
            self._folder = ptf.Unfold(self.model)
        if self.cuda:
            self._folder.cuda()

    def apply(self, *args):
        """Call after folding entire tactic state to force computation"""
        return self._folder.apply(self.model, args)

    def add(self, op, *args):
        return self._folder.add(op, *args)

    def __str__(self):
        return str(self._folder)

# Fold over tactic state

class TacStFolder(object):
    def __init__(self, model, tactr, folder):
        self.model = model    # Only used to access embeddings
        self.tactr = tactr    # Corresponding tactic tree

        self.folder = folder
        self.folded = {}
        if folder.cuda:
            self.torch = torch.cuda
        else:
            self.torch = torch

    def reset(self):
        self.folded = {}

    # -------------------------------------------
    # Tactic state folding

    def fold_tacst(self, tacst):
        """Top-level fold function"""
        gid, ctx, concl_idx, tac = tacst
        env, foldeds = self.fold_ctx(gid, ctx)
        folded = self.fold_concl(gid, env, concl_idx)
        return self.model.pred(self.folder, folded, *foldeds)

    def fold_ctx(self, gid, ctx):
        foldeds = []
        env = FastEnv({}, {}, [], [])
        for ident, typ_idx in ctx:
            folded = self.fold_ctx_ident(gid, env, typ_idx)
            env = env.ctx_extend(Name(ident), folded)
            foldeds += [folded]
        return env, foldeds

    def fold_ctx_ident(self, gid, env, typ_idx):
        # NOTE(deh): Do not need context sharing because of AST sharing
        c = self.tactr.decoder.decode_exp_by_key(typ_idx)
        return self.fold_ast(env, c)

    def fold_concl(self, gid, env, concl_idx):
        # NOTE(deh): Do not need conclusion sharing because of AST sharing
        c = self.tactr.decoder.decode_exp_by_key(concl_idx)
        return self.fold_ast(env, c)

    # -------------------------------------------
    # AST folding

    def fold_ast(self, env, c):
        return self._fold_ast(env, Kind.TERM, c)

    def _fold(self, key, args):
        # for i,arg in enumerate(args):
        #     print(i, arg.shape)

        fold = self.model.ast_emb_func(self.folder, args)
        self.folded[key] = fold
        return fold

    def _fold_ast(self, env, kind, c):
        key = c.tag
        if key in self.folded:
            return self.folded[key]

        # Ordered by number of occurances, better would be a dict.
        typ = type(c)
        if typ is AppExp:
            ev_c = self._fold_ast(env, Kind.TERM, c.c)
            ev_cs = self._fold_asts(env, Kind.TERM, c.cs)
            return self._fold(key, [self.model.app, ev_c, *ev_cs])
        elif typ is ConstExp:
            ev_const = self.fold_const_name(c.const)
            # NOTE(deh): leaving out universe instances on purpose
            # ev_ui = self.fold_ui(c.ui)
            return self._fold(key, [self.model.const, ev_const])
        elif typ is VarExp:
            ev_x = env.lookup_id(Name(c.x))
            return self._fold(key, [self.model.var, ev_x])
        elif typ is ConstructExp:
            ev_ind = self.fold_ind_name(c.ind)
            ev_conid = self.fold_conid_name((c.ind, c.conid))
            # NOTE(deh): leaving out universe instances on purpose
            # ev_ui = self.fold_ui(c.ui)
            return self._fold(key, [self.model.construct, ev_ind, ev_conid])
        elif typ is IndExp:
            ev_ind = self.fold_ind_name(c.ind)
            # NOTE(deh): leaving out universe instances on purpose
            # ev_ui = self.fold_ui(c.ui)
            return self._fold(key, [self.model.ind, ev_ind])
        elif typ is RelExp:
            # NOTE(deh): DeBruinj indicides start at 1 ...
            ev_idx = env.lookup_rel(c.idx - 1)
            return self._fold(key, [self.model.rel, ev_idx])
        elif typ is ProdExp:
            ev_x = self.fold_local_var(c.ty1)
            ev_ty1 = self._fold_ast(env, Kind.TYPE, c.ty1)
            ev_ty2 = self._fold_ast(env.local_extend(c.name, ev_x), Kind.TYPE, c.ty2)
            return self._fold(key, [self.model.prod, ev_ty1, ev_ty2])
        elif typ is LambdaExp:
            ev_x = self.fold_local_var(c.ty)
            ev_ty = self._fold_ast(env, Kind.TERM, c.ty)
            ev_c = self._fold_ast(env.local_extend(c.name, ev_x), Kind.TYPE, c.c)
            return self._fold(key, [self.model.lam, ev_ty, ev_c])
        elif typ is MetaExp:
            assert False, "NOTE(deh): MetaExp should never be in dataset"
        elif typ is EvarExp:
            ev_exk = self.fold_evar_name(c.exk)
            # NOTE(deh): pruposely leaving out cs
            # ev_cs = self._fold_asts(env, Kind.TYPE, c.cs)
            return self._fold(key, [self.model.evar, ev_exk])
        elif typ is SortExp:
            ev_sort = self.fold_sort_name(c.sort)
            return self._fold(key, [self.model.sort, ev_sort])
        elif typ is CastExp:
            ev_c = self._fold_ast(env, Kind.TERM, c.c)
            ev_ty = self._fold_ast(env, Kind.TYPE, c.ty)
            return self._fold(key, [self.model.cast, ev_c, ev_ty])
        elif typ is LetInExp:
            ev_c1 = self._fold_ast(env, Kind.TERM, c.c1)
            ev_ty = self._fold_ast(env, Kind.TYPE, c.ty)
            ev_c2 = self._fold_ast(env.local_extend(c.name, ev_c1), Kind.TERM, c.c2)
            return self._fold(key, [self.model.letin, ev_c1, ev_ty, ev_c2])
        elif typ is CaseExp:
            ev_ret = self._fold_ast(env, Kind.TERM, c.ret)
            ev_match = self._fold_ast(env, Kind.TERM, c.match)
            ev_cases = self._fold_asts(env, Kind.TERM, c.cases)
            return self._fold(key, [self.model.case, ev_ret, ev_match, *ev_cases])
        elif typ is FixExp:
            # 1. Create initial embeddings
            for name in c.names:
                ev = self.fold_fix_name(name)
                # self.fixbody_embed[name] = ev
                env = env.local_extend(name, ev)

            # 2. Use initial embeddings
            ev_tys = []
            ev_cs = []
            for ty, body in zip(c.tys, c.cs):
                ev_tys += [self._fold_ast(env, Kind.TYPE, ty)]
                ev_c = self._fold_ast(env, Kind.TERM, body)
                # TODO(deh): wtf?
                # Tie the knot appropriately
                # self.fix_embed[name] = ev_c
                ev_cs += [ev_c]
            return self._fold(key, [self.model.fix, *ev_tys, *ev_cs])
        elif typ is CoFixExp:
            # NOTE(deh): CoFixExp not in dataset
            raise NameError("NOTE(deh): CoFixExp not in dataset")
        elif typ is ProjExp:
            # NOTE(deh): ProjExp not in dataset
            raise NameError("NOTE(deh): ProjExp not in dataset")
            # ev = self._fold_ast(env, Kind.TERM, c.c)
            # return self._fold(key, [self.model.proj, ev])
        else:
            raise NameError("Kind {} not supported".format(c))

    def _fold_asts(self, env, kind, cs):
        # TODO(deh): may need to fix this for fold to work
        return [self._fold_ast(env, kind, c) for c in cs]

    # -------------------------------------------
    # Global constant folding
    def lookup(self, lt):
        return self.folder.add('embed_lookup_f', autograd.Variable(self.torch.LongTensor([lt])))

    def fold_evar_name(self, exk):
        """Override Me"""
        id = self.model.fix_id('evar', self.model.evar_to_idx[exk])
        return self.lookup(id)

    def fold_const_name(self, const):
        """Override Me"""
        id = self.model.fix_id('const', self.model.const_to_idx[const])
        return self.lookup(id)

    def fold_sort_name(self, sort):
        """Override Me"""
        id = self.model.fix_id('sort', self.model.sort_to_idx[sort])
        return self.lookup(id)

    def fold_ind_name(self, ind):
        """Override Me"""
        id = self.model.fix_id('ind', self.model.ind_to_idx[ind.mutind])
        return self.lookup(id)

    def fold_conid_name(self, ind_and_conid):
        """Override Me"""
        ind, conid = ind_and_conid
        id = self.model.fix_id('conid', self.model.conid_to_idx[(ind.mutind, conid)])
        return self.lookup(id)

    def fold_fix_name(self, name):
        """Override Me"""
        id = self.model.fix_id('fix', self.model.fix_to_idx[name])
        return self.lookup(id)

    # -------------------------------------------
    # Local variable folding

    def fold_local_var(self, ty):
        """Override Me"""
        return self.folder.add('var_normal', self.torch.FloatTensor(1,self.model.D))


class TreeLSTM(nn.Module):
    def __init__(self, state):
        super().__init__()
        self.whx = nn.Linear(state * 2, state *5)

    def forward(self, right_h, right_c, left_h, left_c): #takes x as first arg, h as second
        a, i, f1, f2, o = self.whx(torch.cat([left_h, right_h], dim = -1)).chunk(5, -1)
        c = (a.tanh() * i.sigmoid() + f1.sigmoid() * left_c + f2.sigmoid() * right_c)
        h = o.sigmoid() * c.tanh()
        return h,c
#
# class TreeGRU(nn.Module):
#     def __init__(self, state):
#         super().__init__()
#         self.whx = nn.Linear(state * 2, state * 3)
#         self.
#
#     def forward(self, right_h, left_h):  # takes x as first arg, h as second
#         z, r1, r2 = self.whx(torch.cat([left_h, right_h], dim=-1)).chunk(3, -1)
#
#         c = (a.tanh() * i.sigmoid() + r1.sigmoid() * left_c + r2.sigmoid() * right_c)
#         h = o.sigmoid() * c.tanh()
#         return h, c
# -------------------------------------------------
# Model

class PosEvalModel(nn.Module):
    def __init__(self, sort_to_idx, const_to_idx, ind_to_idx,
                 conid_to_idx, evar_to_idx, fix_to_idx,
                 D=128, state=128, outsize=3, eps=1e-6, ln = False, treelstm = False, lstm = False, dropout = 0.0, attention = False, heads = 1):
        super().__init__()

        # Dimensions
        self.D = D            # Dimension of embeddings
        self.state = state    # Dimension of GRU state

        table_names = ['sort', 'const', 'ind', 'conid', 'evar', 'fix', 'fixbody']
        tables = [sort_to_idx, const_to_idx, ind_to_idx, conid_to_idx, evar_to_idx, fix_to_idx, fix_to_idx]
        shift = 0
        self.shifts = {}
        for table_name, table in zip(table_names, tables):
            self.shifts[table_name] = shift
            shift += len(table)
        # print(self.shifts, shift)
        self.treelstm = treelstm
        self.lstm = lstm
        self.tup = self.treelstm or self.lstm # So, we have hidden, state; instead of just state

        if self.tup:
            self.D = 2*D
        self.embed_table = nn.Embedding(shift, self.D)

        # Embeddings for constants
        self.sort_to_idx = sort_to_idx
        # self.sort_embed = nn.Embedding(len(sort_to_idx), D)
        self.const_to_idx = const_to_idx
        # self.const_embed = nn.Embedding(len(const_to_idx), D)
        self.ind_to_idx = ind_to_idx
        # self.ind_embed = nn.Embedding(len(ind_to_idx), D)
        self.conid_to_idx = conid_to_idx
        # self.conid_embed = nn.Embedding(len(conid_to_idx), D)
        self.evar_to_idx = evar_to_idx
        # self.evar_embed = nn.Embedding(len(evar_to_idx), D)
        self.fix_to_idx = fix_to_idx
        # self.fix_embed = nn.Embedding(len(fix_to_idx), D)
        # self.fixbody_embed = nn.Embedding(len(fix_to_idx), D)

        for attr in ["rel", "var", "evar", "sort", "cast", "prod",
                     "lam", "letin", "app", "const", "ind", "construct",
                     "case", "fix", "cofix", "proj1"]:
            if self.tup:
                self.__setattr__(attr, nn.ParameterList([nn.Parameter(torch.randn(1, state)), nn.Parameter(torch.randn(1, state))]))
            else:
                self.__setattr__(attr, nn.Parameter(torch.randn(1, state)))

        # Sequence models
        seq_args = {'ln': ln, 'tup': self.tup, 'input_dropout': dropout > 0.0}
        if seq_args['ln']:
            # Layer Norm
            self.ast_gamma = nn.Parameter(torch.ones(state))
            self.ast_beta = nn.Parameter(torch.zeros(state))
            self.ctx_gamma = nn.Parameter(torch.ones(state))
            self.ctx_beta = nn.Parameter(torch.zeros(state))
            self.eps = eps

        if seq_args['input_dropout']:
            # Input droput
            self.input_dropout = nn.Dropout(dropout)

        if attention:
            self.m = heads
            self.attn_sv_init = nn.Parameter(torch.zeros(1, heads*state))
            self.attn_q = nn.Linear(state, heads*state)
            self.attn_kv = nn.Linear(state, 2*heads*state)

        if self.tup:
            self.ast_cell_init_state = nn.ParameterList([nn.Parameter(torch.randn(1, state)), nn.Parameter(torch.randn(1, state))])
            self.ctx_cell_init_state = nn.ParameterList([nn.Parameter(torch.randn(1, state)), nn.Parameter(torch.randn(1, state))])
        else:
            self.ast_cell_init_state = nn.Parameter(torch.randn(1, state))
            self.ctx_cell_init_state = nn.Parameter(torch.randn(1, state))

        if self.treelstm:
            self.ast_cell = TreeLSTM(state)
            self.ast_emb_func = lambda folder, xs: seq_embed('ast_tree', folder, xs, self.ast_cell_init_state, **seq_args)
            self.ctx_cell = TreeLSTM(state)
            self.ctx_emb_func = lambda folder, xs: seq_embed('ctx_tree', folder, xs, self.ctx_cell_init_state, **seq_args)
        else:
            if self.lstm:
                self.ast_cell = nn.LSTMCell(state, state)
                self.ctx_cell = nn.LSTMCell(state, state)
                name = "_lstm"
            else:
                # Default is GRU
                self.ast_cell = nn.GRUCell(state, state)
                self.ctx_cell = nn.GRUCell(state, state)
                name = ""
            self.ast_emb_func = lambda folder, xs: seq_embed('ast' + name, folder, xs, self.ast_cell_init_state, **seq_args)
            if not attention:
                self.ctx_emb_func = lambda folder, xs: seq_embed('ctx' + name, folder, xs, self.ctx_cell_init_state, **seq_args)
            else:
                self.ctx_emb_func = lambda folder, xs: seq_sigmoid_attn_embed(folder, xs, self.attn_sv_init, **seq_args)
        self.pred = self.ctx_func
        self.proj = nn.Linear(state + 1, state)
        self.final = nn.Linear(heads*state, outsize)
        self.loss_fn = nn.CrossEntropyLoss()

        # Extra vars
        self.register_buffer('concl_id', torch.ones([1,1]))
        self.register_buffer('state_id', torch.zeros([1,1]))

    # Folder forward functions
    def attn_identity(self, x):
        return x

    def attn_q_f(self, x):
        return self.attn_q(x)

    def attn_sv_f(self, q, x, sv):
        batch, state = x.shape
        # q is [b, m*state], x is [b, state], k,v will bbe [b, m*state]
        k, v = self.attn_kv(x).chunk(2, -1)
        if self.m == 1:
            k = k.unsqueeze(1)
            q = q.unsqueeze(2)
            prod = torch.bmm(k, q).view(batch, 1)/float(np.sqrt(state))
            prsg = prod.sigmoid()
            sv = sv + (prsg * v)
        else:
            k = k.contiguous().view(batch*self.m, 1, state)  # or torch.stack(k.chunk(self.m,-1),0)
            q = q.contiguous().view(batch*self.m, state, 1)
            v = v.contiguous().view(batch*self.m, state)
            prod = torch.bmm(k, q).view(batch*self.m, 1) / float(np.sqrt(state))
            prsg = prod.sigmoid()
            sv = sv + (prsg * v).view(batch, self.m*state)
        # print("prod std dev {}".format(torch.sqrt(torch.mean(prod*prod)).data))
        # print("sigmoid std dev {}".format(torch.sqrt(torch.mean(prsg*prsg)).data))
        return sv

    def input_dropout_f(self, x):
        return self.input_dropout(x)

    def var_normal(self, x):
        if self.tup:
            return autograd.Variable(x.normal_(), requires_grad = False).chunk(2,-1)
        else:
            return autograd.Variable(x.normal_(), requires_grad = False)

    def identity(self, x):
        return x

    def tup_identity(self, *args):
        return args

    def fix_id(self, table_name, id):
        # print(table_name, id, )
        # print(self.embed_table(autograd.Variable(torch.LongTensor([self.shifts[table_name] + id]))))
        return self.shifts[table_name] + id

    def embed_lookup_f(self, id):
        if self.tup:
            return self.embed_table(id).chunk(2,-1)
        else:
            return self.embed_table(id)

    def ast_cell_f(self, x, hidden):
        hidden = self.ast_cell(x, hidden)
        return hidden

    def ctx_cell_f(self, x, hidden):
        hidden = self.ctx_cell(x, hidden)
        return hidden

    def ast_lstm_cell_f(self, right_h, right_c, left_h, left_c):
        hidden = self.ast_cell(right_h, (left_h, left_c))
        return hidden

    def ctx_lstm_cell_f(self, right_h, right_c, left_h, left_c):
        hidden = self.ctx_cell(right_h, (left_h, left_c))
        return hidden

    def ast_tree_cell_f(self, right_h, right_c, left_h, left_c):
        out = self.ast_cell(right_h, right_c, left_h, left_c)
        return out

    def ctx_tree_cell_f(self, right_h, right_c, left_h, left_c):
        out = self.ctx_cell(right_h, right_c, left_h, left_c)
        return out

    def ast_ln_f(self, x):
        mean = x.mean(-1, keepdim=True)
        std = x.std(-1, keepdim=True)
        return self.ast_gamma * (x - mean) / (std + self.eps) + self.ast_beta

    def ctx_ln_f(self, x):
        mean = x.mean(-1, keepdim=True)
        std = x.std(-1, keepdim=True)
        return self.ctx_gamma * (x - mean) / (std + self.eps) + self.ctx_beta

    def final_f(self, x):
        return self.final(x)

    def proj_f(self, *xs):
        x = torch.cat(xs, dim = -1)
        return self.proj(x)

    # Folder helper functions, call the forward functions
    def mask(self, folder, xs):
        # First element is conclu, rest is state
        projs = []
        for i,x in enumerate(xs):
            if i == 0:
                id = self.concl_id
            else:
                id = self.state_id
            projs.append(folder.add('proj_f', x, autograd.Variable(id)))
        return projs

    def ctx_func(self, folder, *tacst_evs):
        if self.tup:
            x_hidden, x_cell = list(zip(*tacst_evs))
            x_hidden = self.mask(folder, x_hidden)
            xs = list(zip(x_hidden, x_cell))
        else:
            xs = self.mask(folder, tacst_evs)
        x = self.ctx_emb_func(folder, xs)
        # Final layer for logits
        if self.tup:
            x = x[0]
        x = folder.add('final_f', x)
        return x




