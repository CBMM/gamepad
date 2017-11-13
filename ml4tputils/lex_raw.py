from lib.myfile import MyFile
from coq_ast import *

"""
[Note]

Goal: String -> [TacStDecl]

AST:
[TacStDecl] ::= decls
TacStDecl ::= decl

BNF:
decls ::= decl | decl '\n' decls
decl ::= hdr '\n' ctx '============================' '\n' goal

ctx ::= ldecl | ldecl '\n' ctx
ldecl ::= id ':' string '\n'

hdr ::= kind '{!}' tac '{!}' full_tac '{!}' int '{!}' int
kind ::= 'AFTER' | 'BEFORE'
tac ::= string
full_tac ::= string
int ::= [0-9]+
"""


# -------------------------------------------------
# Tokens

TOK_SEP = "{!}"
TOK_DIV = "============================"
TOK_BEFORE = "before"
TOK_AFTER = "after"
TOK_BEG_TAC_ST = "begin(tacst)"
TOK_END_TAC_ST = "end(tacst)"
TOK_BEG_SUB_PF = "begin(subpf)"
TOK_END_SUB_PF = "end(subpf)"
TOK_BEG_PF = "begin(pf)"
TOK_END_PF = "end(pf)"
TOK_TYPS = "Typs"
TOK_BODS = "Bods"
TOK_CONSTRS = "Constrs"


# -------------------------------------------------
# Data structures

GID_SOLVED = -1
GID_FAILED = -2

class TacStHdr(object):
    """
    Contains the header for a tactic state declaration.
    """
    def __init__(self, mode, tac, kind, ftac, gid, ngs, loc, uid):
        self.mode = mode
        self.tac = tac
        self.kind = kind
        self.ftac = ftac
        self.gid = gid
        self.ngs = ngs
        self.loc = loc
        self.uid = uid

    def __str__(self):
        return "({} tac: {}  ftac: {}  gid: {}  ngs: {}  uid: {})".format(
               self.mode, self.tac, self.ftac, self.gid, self.ngs, self.uid)


class TacStDecl(object):
    """
    TacStDecl = 'begin(tacst)' ... 'end(tacst)'
    """
    def __init__(self, tac_st_hdr, ctx, goal, ast_ctx, ast_goal):
        self.hdr = tac_st_hdr
        self.ctx = ctx
        self.goal = goal
        self.ast_ctx = ast_ctx
        self.ast_goal = ast_goal

    def dump(self):
        return "{}\n{}\n{}".format(str(self.hdr), str(self.ctx),
                                   str(self.goal))

    def __str__(self):
        if self.hdr.mode == TOK_BEFORE:
            return "B(uid={}, gid={}, tac={}, loc={})".format(self.hdr.uid, self.hdr.gid, self.hdr.tac, self.hdr.loc)
        elif self.hdr.mode == TOK_AFTER:
            return "A(uid={}, gid={}, tac={}, loc={})".format(self.hdr.uid, self.hdr.gid, self.hdr.tac, self.hdr.loc)
        else:
            return "E(uid={}, gid={}, tac={}, loc={})".format(self.hdr.uid, self.hdr.gid, self.hdr.tac, self.hdr.loc)

    def __hash__(self):
        msg = "{}{}".format(self.hdr.loc, self.hdr.gid)
        return int.from_bytes(msg.encode(), "little")


class LemTacSt(object):
    """
    Contains the lemma and the sequence of tactic states associated with it.
    """
    def __init__(self, name, decls, typs_table, bods_table, constrs_table):
        for decl in decls:
            assert isinstance(decl, TacStDecl)

        self.name = name
        self.decls = decls
        self.typs_table = typs_table         # Dict[id, int]
        self.bods_table = bods_table         # Dict[id, int]
        # self.constrs_table = constrs_table   # Dict[int, string]
        self.recon = CoqExpRecon(constrs_table)

    def typ2ast(self, key):
        idx = self.typs_table[key]
        return self.recon_ast(idx)

    def bod2ast(self, key):
        idx = self.bods_table[key]
        return self.recon_ast(idx)

    def __str__(self):
        msg = "\n".join([str(decl) for decl in self.decls])
        return "{}<{}>".format(self.name, msg)


# -------------------------------------------------
# Parsing

class TacStParser(object):
    def __init__(self, filename, f_log=False):
        self.filename = filename
        self.f_head = MyFile(filename)
        self.f_log = f_log
        self.log = []
        self.lems = []
        self.decls = []
        self.exhausted = False

        self.typs_table = {}
        self.bods_table = {}
        self.constrs_table = {}

    def _mylog(self, msg, f_log=False):
        if f_log or self.f_log:
            # self.log.append(msg)
            print(msg)

    def parse_local_decl(self):
        # Internal
        f_head = self.f_head
        self._mylog("@parse_local_decl:before<{}>".format(f_head.peek_line()))

        # Parse local decl
        ldecl = f_head.consume_line()
        idx = ldecl.find(':')
        if idx < 0:
            raise NameError("Parsing local declaration but found {}".
                            format(ldecl))
        name = ldecl[:idx].strip()
        typ = ldecl[idx + 1:].strip()

        # Parse rest of type it is on newline
        line = f_head.peek_line()
        while line != TOK_DIV and line.find(':') < 0:
            typ += " " + line.strip()
            line = f_head.advance_line()
        return (name, typ)

    def parse_local_ctx(self):
        # Internal
        f_head = self.f_head
        self._mylog("@parse_local_ctx:before<{}>".format(f_head.peek_line()))

        # Parse local context
        local_decls = []
        line = f_head.peek_line()
        while line.find(':') >= 0:
            name, typ = self.parse_local_decl()
            local_decls += [(name, typ)]
            line = f_head.peek_line()
        return local_decls

    def parse_newline(self):
        # Internal
        f_head = self.f_head
        self._mylog("@parse_newline:before<{}>".format(f_head.peek_line()))

        # Parse new line
        line = f_head.consume_line()
        return line

    def parse_pf_div(self):
        # Internal
        f_head = self.f_head
        self._mylog("@parse_pf_div:before<{}>".format(f_head.peek_line()))

        # Parse proof divider
        line = f_head.consume_line()
        if line != TOK_DIV:
            raise NameError("Found {} instead of {}".format(line, TOK_DIV))
        return line

    def parse_goal(self):
        # Internal
        f_head = self.f_head
        self._mylog("@parse_goal:before<{}>".format(f_head.peek_line()))

        # Parse goal
        goal = f_head.consume_line()
        line = f_head.peek_line()
        # while not line.startswith(TOK_END_TAC_ST):
        while not line.startswith(TOK_SEP):
            goal += line
            line = f_head.advance_line()
        return goal

    def parse_local_ast_ctx(self):
        # Internal
        f_head = self.f_head
        self._mylog("@parse_local_ast_ctx:before<{}>".format(f_head.peek_line()))

        # Parse local ctx
        line = f_head.consume_line()
        xs = [x.strip() for x in line.split(",")]
        return xs

    def parse_ast_goal(self):
        # Internal
        f_head = self.f_head
        self._mylog("@parse_ast_goal:before<{}>".format(f_head.peek_line()))

        goal = f_head.consume_line()
        return int(goal)

    def parse_decl(self, depth, mode, tac, kind, loc):
        # Internal
        f_head = self.f_head
        self._mylog("@parse_decl:before<{}>".format(f_head.peek_line()))

        # Parse declaration
        if f_head.peek_line().startswith("ngs=0"):
            # Parse rest of header
            f_head.consume_line()  # ngs=0
            f_head.consume_line()  # end(tacst)

            # Unpack
            tac_st_hdr = TacStHdr(mode, tac, kind, "", GID_SOLVED, 0, loc, depth)
            ctx = []
            goal = "ML4TP_SOLVED"
            ast_ctx = []
            ast_goal = -1
        elif TOK_SEP in f_head.peek_line():
            # Parse rest of header
            hdr = f_head.consume_line()
            toks = hdr.split(TOK_SEP)
            while len(toks) < 3:
                line = f_head.consume_line()
                hdr += line
                toks = hdr.split(TOK_SEP)
            ngs = int(toks[0].strip())
            ftac = toks[1].strip()
            gid = int(toks[2].strip())

            # Unpack (note that we handle error and success here)
            tac_st_hdr = TacStHdr(mode, tac, kind, ftac, gid, ngs, loc, depth)
            ctx = self.parse_local_ctx()
            self.parse_pf_div()
            goal = self.parse_goal()
            f_head.consume_line()   # NOTE(deh): Parse separator {!}
            ast_ctx = self.parse_local_ast_ctx()
            self.parse_pf_div()
            ast_goal = self.parse_ast_goal()
        else:
            raise NameError("Parsing error @line{}: {}".format(f_head.line, f_head.peek_line()))
        return TacStDecl(tac_st_hdr, ctx, goal, ast_ctx, ast_goal)

    def parse_begin_pf(self):
        # Internal
        f_head = self.f_head
        self._mylog("@parse_begin_pf:before<{}>".format(f_head.peek_line()))

        # Parse
        line = f_head.consume_line()
        toks = line.split(TOK_SEP)
        lem_name = toks[2].strip()

        self._mylog("progress: {:4.2f}% @ {}".format(
                    f_head.progress(), lem_name), True)
        return lem_name

    def parse_begsubpf(self):
        # Internal
        f_head = self.f_head
        self._mylog("@parse_begsubpf:before<{}>".format(f_head.peek_line()))

        # Parse
        return f_head.consume_line()

    def parse_endsubpf(self):
        # Internal
        f_head = self.f_head
        self._mylog("@parse_endsubpf:before<{}>".format(f_head.peek_line()))

        # Parse
        return f_head.consume_line()

    def parse_qed(self):
        # Internal
        f_head = self.f_head
        self._mylog("@parse_qed:before<{}>".format(f_head.peek_line()))

        # Parse
        return f_head.consume_line()

    def parse_begtacst(self):
        # Internal
        f_head = self.f_head
        self._mylog("@parse_begtacst:before<{}>".format(f_head.peek_line()))

        # Parse header
        hdr = f_head.consume_line()
        toks = hdr.split(TOK_SEP)
        while len(toks) < 6:
            line = f_head.consume_line()
            hdr += line
            toks = hdr.split(TOK_SEP)

        # Unpack header
        depth = int(toks[1].strip())
        mode = toks[2].strip()
        tac = toks[3].strip()
        kind = toks[4].strip()
        loc = toks[5].strip()

        return (depth, mode, tac, kind, loc)

    def parse_endtacst(self):
        # Internal
        f_head = self.f_head
        self._mylog("@parse_endtacst:before<{}>".format(f_head.peek_line()))

        # Parse
        return f_head.consume_line()

    def parse_typs_table(self):
        # Internal
        f_head = self.f_head
        self._mylog("@parse_typs_table:before<{}>".format(f_head.peek_line()))

        # Parse identifier to expression identifier
        _ = f_head.consume_line()
        while not f_head.peek_line().startswith(TOK_BODS):
            hdr = f_head.consume_line()
            end = hdr.find(":")
            x = hdr[:end].strip()
            edx = hdr[end+1:].strip()
            self.typs_table[x] = edx

    def parse_bods_table(self):
        # Internal
        f_head = self.f_head
        self._mylog("@parse_bods_table:before<{}>".format(f_head.peek_line()))

        # Parse identifier to expression identifier
        _ = f_head.consume_line()
        while not f_head.peek_line().startswith(TOK_CONSTRS):
            hdr = f_head.consume_line()
            end = hdr.find(":")
            x = hdr[:end].strip()
            bdx = hdr[end+1:].strip()
            self.bods_table[x] = bdx

    def parse_constrs_table(self):
        # Internal
        f_head = self.f_head
        self._mylog("@parse_constrs_table:before<{}>".format(f_head.peek_line()))

        # Parse expression identifier to low-level constr expression
        _ = f_head.consume_line()
        while not f_head.peek_line().startswith(TOK_END_PF):
            hdr = f_head.consume_line()
            end = hdr.find(":")
            edx = hdr[:end].strip()
            low_constr = hdr[end+1:].strip()
            self.constrs_table[edx] = low_constr

    def parse_lemma(self):
        """
        Parse tactic states for an entire lemma.
        """
        # Internal
        f_head = self.f_head
        self._mylog("parse_lemma<{}>".format(f_head.peek_line()))

        if self.exhausted:
            raise NameError("Already parsed file {}".format(self.filename))

        # Parse
        line = f_head.raw_peek_line()
        while line != "":
            line = line.rstrip()
            if line.startswith(TOK_BEG_PF):
                lem_name = self.parse_begin_pf()
                # TODO(deh): this does not handle opening a proof
                # within a proof
                self.decls = []
            elif line.startswith(TOK_END_PF):
                self.parse_qed()
                # Accumulate lemma
                lemma = LemTacSt(lem_name, self.decls, self.typs_table,
                                 self.bods_table, self.constrs_table)
                self.lems.append(lemma)
                if f_head.raw_peek_line() == "":
                    self.exhausted = True

                # Reset tables for new lemma
                self.typs_table = {}
                self.bods_table = {}
                self.constrs_table = {}
                
                return lemma
            elif line.startswith(TOK_BEG_SUB_PF):
                self.parse_begsubpf()
                # TODO(deh): keep track of this?
            elif line.startswith(TOK_END_SUB_PF):
                self.parse_endsubpf()
                # TODO(deh): keep track of this?
            elif line.startswith(TOK_BEG_TAC_ST):
                depth, mode, tac, kind, loc = self.parse_begtacst()
                decl = self.parse_decl(depth, mode, tac, kind, loc)
                self.decls += [decl]
            elif line.startswith(TOK_END_TAC_ST):
                self.parse_endtacst()
            elif line.startswith(TOK_TYPS):
                self.parse_typs_table()
            elif line.startswith(TOK_BODS):
                self.parse_bods_table()
            elif line.startswith(TOK_CONSTRS):
                self.parse_constrs_table()
            elif line.startswith("AfterHOHOHO"):
                # TODO(deh): Kludge, fix coq
                self.f_head.consume_line()
            else:
                raise NameError("Parsing error at line {}: {}".format(
                                f_head.line, f_head.peek_line()))
            line = f_head.raw_peek_line()

    def parse_file(self):
        """
        Top-level parse function.
        """
        # Internal
        f_head = self.f_head
        self._mylog("parse<{}>".format(f_head.peek_line()))

        if self.exhausted:
            raise NameError("Already parsed file {}".format(self.filename))

        # Parse
        line = f_head.raw_peek_line()
        while line != "":
            self.parse_lemma()
            line = f_head.raw_peek_line()
        self.exhausted = True
        return self.lems
