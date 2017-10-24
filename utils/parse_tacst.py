from lib.myiter import MyIter
from parse_raw import *

"""
[Note]

Goal: [TacStDecl] -> [Tac]

AST:
Tacs ::= Tac | Tac Tacs
Tac ::= intro(alias, core)
      | reflexivity(alias, core)
      | have(alias, plugin, body)
      | generic(tac)
"""

# TODO(deh): new proof format that (hopefully) gives all before/afters
#            should simplify parsing


# -------------------------------------------------
# Data structures

class Tac(object):
    def __init__(self, uid, terminal=False):
        self.uid = uid
        self.terminal = terminal

    def has_subtac(self):
        # type: Tac -> bool
        raise NotImplementedError

    def in_edge(self):
        # type: Tac -> GoalId
        raise NotImplementedError

    def out_edges(self):
        # type: Tac -> [GoalId]
        raise NotImplementedError

    def __hash__(self):
        return self.uid


class FixedTac(Tac):
    def __init__(self, uid, name, alias, core, terminal=False):
        assert isinstance(name, str)
        assert isinstance(alias[0], TacStDecl)
        assert isinstance(alias[1], TacStDecl)
        assert isinstance(core[0], TacStDecl)
        assert isinstance(core[1], TacStDecl)

        super().__init__(uid, terminal)
        self.name = name
        self.alias = alias
        self.core = core

    def has_subtac(self):
        return False

    def in_edge(self):
        return self.alias[0].hdr.gid

    def out_edges(self):
        return [self.core[1].hdr.gid]

    def __str__(self):
        es = [str(self.alias[0]), str(self.core[0]),
              str(self.core[1]), str(self.alias[1])]
        return "{}({}; {})".format(self.name, self.uid, ", ".join(es))


class VaryTac(Tac):
    def __init__(self, uid, name, alias, bf_core, af_cores, terminal=False):
        assert isinstance(alias[0], TacStDecl)
        assert isinstance(alias[1], TacStDecl)
        assert isinstance(bf_core, TacStDecl)
        for after in af_cores:
            assert isinstance(after, TacStDecl)

        super().__init__(uid, terminal)
        self.name = name
        self.alias = alias
        self.bf_core = bf_core
        self.af_cores = af_cores

    def has_subtac(self):
        return False

    def in_edge(self):
        return self.before.hdr.gid

    def out_edges(self):
        return [after.hdr.gid for after in self.af_cores]

    def __str__(self):
        ps1 = [str(self.alias[0]), str(self.alias[1]), str(self.bf_core)]
        ps2 = [str(after) for after in self.af_cores]
        return "{}({}; {})".format(self.name, self.uid, ", ".join(ps1 + ps2))


class FixedNestedTac(Tac):
    def __init__(self, uid, name, alias, core, body):
        assert isinstance(alias[0], TacStDecl)
        assert isinstance(alias[1], TacStDecl)
        assert isinstance(core[0], TacStDecl)
        assert isinstance(core[1], TacStDecl)
        for tac in body:
            assert isinstance(tac, Tac)

        super().__init__(uid)
        self.name = name
        self.alias = alias
        self.core = core
        self.body = body

    def has_subtac(self):
        return True

    def in_edge(self):
        return self.alias[0].hdr.gid

    def out_edges(self):
        return [self.core[1].hdr.gid]

    def __str__(self):
        es = [str(self.alias[0]), str(self.core[0]),
              str(self.core[1]), str(self.alias[1])]
        body = [str(tac) for tac in self.body]
        return "{}({}; {}; {})".format(self.name, self.uid, ", ".join(es),
                                       ", ".join(body))


class VaryNestedTac(Tac):
    def __init__(self, uid, name, bf_alias, bf_core,
                 af_cores, af_aliases, body, terminal=False):
        assert isinstance(bf_alias, TacStDecl)
        assert isinstance(bf_core, TacStDecl)
        for after in af_cores:
            assert isinstance(after, TacStDecl)
        for after in af_aliases:
            assert isinstance(after, TacStDecl)
        for tac in body:
            assert isinstance(tac, Tac)

        super().__init__(uid, terminal)
        self.name = name
        self.bf_alias = bf_alias
        self.bf_core = bf_core
        self.af_cores = af_cores
        self.af_aliases = af_aliases
        self.body = body

    def has_subtac(self):
        return True

    def in_edge(self):
        return self.bf_alias.hdr.gid

    def out_edges(self):
        return [after.hdr.gid for after in self.af_aliases]

    def __str__(self):
        ps = ["({}, {})".format(self.bf_alias, after)
              for after in self.af_aliases]
        body = ", ".join([str(x) for x in self.body])
        return "{}({}; {}; {})".format(self.name, self.uid,
                                       ", ".join(ps), body)


class NestTermTac(Tac):
    def __init__(self, uid, alias_name, core_name, alias, core, extra):
        assert isinstance(alias, TacStDecl)
        assert isinstance(core, TacStDecl)
        for decl in extra:
            assert isinstance(decl, TacStDecl)

        super().__init__(uid)
        self.alias_name = alias_name
        self.core_name = core_name
        self.alias = alias
        self.core = core
        self.extra = extra

    def has_subtac(self):
        return False

    def in_edge(self):
        return self.alias.hdr.gid

    def out_edges(self):
        return [self.core.hdr.gid]

    def __str__(self):
        es = [str(self.alias), str(self.core)]
        return "{}({}; {})".format(self.alias_name, self.uid, ", ".join(es))


class SsrtclseqTac(Tac):
    def __init__(self, uid, core, body):
        assert isinstance(core[0], TacStDecl)
        assert isinstance(core[1], TacStDecl)
        for tac in body:
            assert isinstance(tac, Tac)

        super().__init__(uid)
        self.core = core
        self.body = body

    def has_subtac(self):
        return True

    def in_edge(self):
        return self.core[0].hdr.gid

    def out_edges(self):
        return [self.core[1].hdr.gid]

    def __str__(self):
        es = [str(self.core[0]), str(self.core[1])]
        body = [str(tac) for tac in self.body]
        return "Srrtclseq({}; {}; {})".format(self.uid, ", ".join(es),
                                              ", ".join(body))


class SsrtcldoTac(Tac):
    def __init__(self, uid, core):
        assert isinstance(core, TacStDecl)

        super().__init__(uid)
        self.core = core

    def has_subtac(self):
        return False

    def in_edge(self):
        return self.core.hdr.gid

    def out_edges(self):
        return [self.core.hdr.gid]

    def __str__(self):
        return "Srrtcldo({}; {})".format(self.uid, str(self.core))


# TODO(deh): deprecate
class SsrhaveTac(Tac):
    def __init__(self, uid, alias, core, body):
        assert isinstance(alias[0], TacStDecl)
        assert isinstance(alias[1], TacStDecl)
        assert isinstance(core[0], TacStDecl)
        assert isinstance(core[1], TacStDecl)
        for tac in body:
            assert isinstance(tac, Tac)

        super().__init__(uid)
        self.alias = alias
        self.core = core
        self.body = body

    def has_subtac(self):
        return True

    def in_edge(self):
        return self.alias[0].hdr.gid

    def out_edges(self):
        return [self.core[1].hdr.gid]

    def __str__(self):
        es = [str(self.alias[0]), str(self.core[0]),
              str(self.core[1]), str(self.alias[1])]
        body = [str(tac) for tac in self.body]
        return "Srrhave({}; {}; {})".format(self.uid, ", ".join(es),
                                            ", ".join(body))


class GenericTac(Tac):
    def __init__(self, uid, before, afters, terminal=False):
        assert isinstance(before, TacStDecl)
        for after in afters:
            assert isinstance(after, TacStDecl)

        super().__init__(uid, terminal)
        self.before = before
        self.afters = afters

    def has_subtac(self):
        return False

    def in_edge(self):
        return self.before.hdr.gid

    def out_edges(self):
        return [after.hdr.gid for after in self.afters]

    def __str__(self):
        if not self.afters:
            return "Terminal({}; {})".format(self.uid, str(self.before))
        elif len(self.afters) == 1:
            return "Generic({}; {}, {})".format(self.uid, str(self.before),
                                                str(self.afters[0]))
        else:
            ps = ["({}, {})".format(self.before, after)
                  for after in self.afters]
            return "Generic({}; {})".format(self.uid, ", ".join(ps))


# -------------------------------------------------
# Parsing

class TacTreeParser(object):
    def __init__(self, lemma, f_log=False):
        assert isinstance(lemma, LemTacSt)

        self.lemma = lemma
        self.it = MyIter(lemma.decls)
        self.log = []
        self.f_log = f_log
        self.uidcnt = 0
        self.depth = 0

    def _mylog(self, msg, f_log=False):
        if f_log or self.f_log:
            # self.log.append(msg)
            print(" " * (2 * self.depth) + str(msg))

    def _getuid(self):
        uid = self.uidcnt
        self.uidcnt += 1
        return uid

    def parse_fixed_stk(self, name, terminal=False):
        """
        before(name)
          before(name@0)
          after(name@0)
        after(name)
        """
        # Internal
        it = self.it
        self._mylog("@parse_fixed_stk:before<{}>".format(it.peek()))

        # Reconstruct quad tactic that is nested
        bf_name = next(it)
        bf_name0 = next(it)
        af_name0 = next(it)
        af_name = next(it)
        return FixedTac(self._getuid(), name,
                        (bf_name, af_name), (bf_name0, af_name0), terminal)

    def parse_fixed_seq(self, name, terminal=False):
        """
        before(name)
        after(name)
        before(name@0)
        after(name@0)
        """
        # Internal
        it = self.it
        self._mylog("@parse_fixed_seq:before<{}>".format(it.peek()))

        # Reconstruct quad tactic that is sequential
        bf_name = next(it)
        af_name = next(it)
        bf_name0 = next(it)
        af_name0 = next(it)
        return FixedTac(self._getuid(), name,
                        (bf_name, af_name), (bf_name0, af_name0), terminal)

    def parse_vary_seq(self, name, terminal=False):
        """
        before(name)
        after(name)
        before(name0)
        after(name0-1)
        after(name0-n)
        """
        # Internal
        it = self.it
        self._mylog("@parse_vary_seq:before<{}>".format(it.peek()))

        # Reconstruct header
        bf_name = next(it)
        af_name = next(it)
        bf_name0 = next(it)

        # Reconstruct tail
        acc = []
        terminal = False
        if not it.has_next():
            # TODO(deh): kludge?
            self._mylog("Terminal kludge1?")
            terminal = True
        elif it.peek().hdr.ngs == 0:
            # Parse terminal state
            self._mylog("Terminal number of goals is 0")
            terminal = True
            acc += [next(it)]
        else:
            # Parse constant or expanding number of goals
            ngs = it.peek().hdr.ngs
            for _ in range(0, ngs - bf_name0.hdr.ngs + 1):
                # decl_p = next(it)
                acc += [next(it)]
        return VaryTac(self._getuid(), name, (bf_name, af_name),
                       bf_name0, acc, terminal)

    def parse_nestterm(self, alias_name, core_name):
        """
        before(discriminate)
          before(discriminate@0)
          [after(discriminate@0)]
        [after(discriminate)]
        """
        # Internal
        it = self.it
        self._mylog("@parse_nestterm:before<{}>".format(it.peek()))

        bf_name = next(it)
        bf_name0 = next(it)
        extra = []
        if it.has_next() and \
           it.peek().hdr.tac.startswith(core_name):
            af_name0 = next(it)
            extra += [af_name0]
            if it.has_next() and \
               it.peek().hdr.tac.startswith(alias_name):
                af_name = next(it)
                extra += [af_name]
        return NestTermTac(self._getuid(), alias_name, core_name,
                           bf_name, bf_name0, extra)

    def parse_fixed_stk_nested(self, name):
        """
        before(name)
          before(name@0)
            TacTree
          after(name@0)
        after(name)
        """
        # Internal
        it = self.it
        self._mylog("@parse_fixed_stk_nested:before<{}>".format(it.peek()))

        # Reconstruct Ssreflect have tactic
        bf_name = next(it)
        bf_name0 = next(it)
        self.depth += 1
        body = self.parse_tactree()
        self.depth -= 1
        af_name0 = next(it)
        af_name = next(it)
        return FixedNestedTac(self._getuid(), name, (bf_name, af_name),
                              (bf_name0, af_name0), body)

    def parse_vary_stk_nested(self, name):
        """
        before(name)
          before(name@0)
            TacTree
          after(name@0-1)
          ...
          after(name@0-n)
        after(name-1)
        ...
        after(name-n)
        """
        # Internal
        it = self.it
        self._mylog("@parse_vary_stk_nested:before<{}>".format(it.peek()))

        # Reconstruct tactic header
        bf_name = next(it)
        bf_name0 = next(it)
        body = self.parse_tactree()

        # Reconstruct tactic tail
        acc0 = []
        acc = []
        terminal = False
        if not it.has_next():
            # TODO(deh): kludge? is this necessary
            self._mylog("Terminal kludge?")
            terminal = True
        elif it.peek().hdr.ngs == 0:
            # Parse terminal state
            self._mylog("Terminal number of goals is 0")
            terminal = True
            acc0 += [next(it)]
            acc += [next(it)]
        else:
            # Parse constant or expanding number of goals
            ngs = it.peek().hdr.ngs
            for _ in range(0, ngs - bf_name0.hdr.ngs + 1):
                # decl_p = next(it)
                acc0 += [next(it)]
            for _ in range(0, ngs - bf_name.hdr.ngs + 1):
                # decl_p = next(it)
                acc += [next(it)]
        return VaryNestedTac(self._getuid(), name, bf_name, bf_name0,
                             acc0, acc, body, terminal)

    def parse_ssrtclseq(self):
        """
        before(ssrtclseq@0)
          TacTree
        after(ssrtclseq@0)
        """
        # Internal
        it = self.it
        self._mylog("@parse_srrtclseq:before<{}>".format(it.peek()))

        # Reconstruct Ssreflect have tactic
        bf_ssrtclseq0 = next(it)
        self.depth += 1
        body = self.parse_tactree()
        self.depth -= 1
        af_ssrtclseq0 = next(it)
        return SsrtclseqTac(self._getuid(), (bf_ssrtclseq0, af_ssrtclseq0),
                            body)

    def parse_ssrtcldo(self):
        """
        before(ssrtcldo@0)
        """
        # Internal
        it = self.it
        self._mylog("@parse_srrtcldo:before<{}>".format(it.peek()))

        # Reconstruct Ssreflect have tactic
        bf_ssrtcldo0 = next(it)
        return SsrtcldoTac(self._getuid(), bf_ssrtcldo0)

    def parse_generic(self):
        # Internal
        it = self.it
        self._mylog("@parse_generic:before<{}>".format(it.peek()))

        # Reconstruct base tactic
        acc = []
        decl = next(it)
        terminal = False
        if not it.has_next():
            # TODO(deh): kludge?
            self._mylog("Terminal kludge1?")
            terminal = True
        elif decl.hdr.tac != it.peek().hdr.tac:
            # TODO(deh): kludge?
            self._mylog("Terminal kludge2?")
            terminal = True
        elif it.peek().hdr.ngs == 0:
            # Parse terminal state
            self._mylog("Terminal number of goals is 0")
            terminal = True
            acc += [next(it)]
        else:
            # Parse constant or expanding number of goals
            ngs = it.peek().hdr.ngs
            for _ in range(0, ngs - decl.hdr.ngs + 1):
                # decl_p = next(it)
                acc += [next(it)]
        return GenericTac(self._getuid(), decl, acc, terminal)

    def parse_tactree(self):
        """
        Top-level parsing function.
        """
        # Internal
        it = self.it
        self._mylog("@parse_tactree:before<{}>".format(it.peek()))

        # Reconstruct tactic tree
        acc = []
        while it.has_next():
            decl = it.peek()

            # ----------------------------------------------
            # Coq tactics

            # Non-terminal, fixed-width, stack cases
            if decl.hdr.mode == TOK_BEFORE and \
               decl.hdr.tac.startswith("intro") and \
               not decl.hdr.tac.startswith("intros"):
                acc += [self.parse_fixed_stk("Intro")]
            elif decl.hdr.mode == TOK_BEFORE and \
                 decl.hdr.tac.startswith("case"):
                acc += [self.parse_fixed_stk("Case")]

            # Terminal, fixed-width, stack cases
            elif decl.hdr.mode == TOK_BEFORE and \
                 decl.hdr.tac.startswith("trivial"):
                acc += [self.parse_fixed_stk("trivial", True)]
            elif decl.hdr.mode == TOK_BEFORE and \
                 decl.hdr.tac.startswith("exact"):
                acc += [self.parse_fixed_stk("Exact", True)]

            # Terminal, fixed-width, sequential cases
            elif decl.hdr.mode == TOK_BEFORE and \
                 decl.hdr.tac.startswith("assumption"):
                acc += [self.parse_fixed_seq("Assumption", True)]
            elif decl.hdr.mode == TOK_BEFORE and \
                 decl.hdr.tac.startswith("reflexivity"):
                acc += [self.parse_fixed_seq("Reflexivity", True)]

            # Variable-width, sequential cases
            elif decl.hdr.mode == TOK_BEFORE and \
                 decl.hdr.tac.startswith("split"):
                acc += [self.parse_vary_seq("Split")]

            # TODO(deh): look at this again, terminal optional nested cases
            elif decl.hdr.mode == TOK_BEFORE and \
                 decl.hdr.tac.startswith("discriminate"):
                acc += [self.parse_nestterm("discriminate",
                                            "<extratactics::discriminate@0>")]

            # See generic for variable-width, sequential cases

            # ----------------------------------------------
            # Ssreflect tactics

            # Non-terminal, fixed-width, stack cases
            elif decl.hdr.mode == TOK_BEFORE and \
                 decl.hdr.tac.startswith("move (ssrmovearg) (ssrclauses)"):
                acc += [self.parse_fixed_stk("Ssrmove")]

            # ----------------------
            # Nested cases (paired)

            # Fixed-width, nested cases
            elif decl.hdr.mode == TOK_BEFORE and \
                 decl.hdr.tac.startswith("by (ssrhintarg)"):
                acc += [self.parse_fixed_stk_nested("Ssrby")]
            elif decl.hdr.mode == TOK_AFTER and \
                 decl.hdr.tac.startswith("<ssreflect_plugin::ssrtclby@0>"):
                return acc

            elif decl.hdr.mode == TOK_BEFORE and \
                 decl.hdr.tac.startswith("exact (ssrexactarg)"):
                acc += [self.parse_fixed_stk_nested("Ssrexact")]
            elif decl.hdr.mode == TOK_BEFORE and \
                 decl.hdr.tac.startswith("<ssreflect_plugin::ssrexact@0>"):
                return acc

            elif decl.hdr.mode == TOK_BEFORE and \
                 decl.hdr.tac.startswith("have (ssrhavefwdwbinders)"):
                acc += [self.parse_fixed_stk_nested("Ssrhave")]
            elif decl.hdr.mode == TOK_AFTER and \
                 decl.hdr.tac.startswith("<ssreflect_plugin::ssrhave@0>"):
                return acc

            # Variable-width, nested cases
            elif decl.hdr.mode == TOK_BEFORE and \
                 decl.hdr.tac.startswith("apply (ssrapplyarg)"):
                acc += [self.parse_vary_stk_nested("Ssrapply")]
            elif decl.hdr.mode == TOK_AFTER and \
                 decl.hdr.tac.startswith("<ssreflect_plugin::ssrapply@0>"):
                return acc

            elif decl.hdr.mode == TOK_BEFORE and \
                 decl.hdr.tac.startswith("rewrite (ssrrwargs) (ssrclauses)"):
                acc += [self.parse_vary_stk_nested("Ssrrewrite")]
            elif decl.hdr.mode == TOK_AFTER and \
                 decl.hdr.tac.startswith("<ssreflect_plugin::ssrrewrite@0>"):
                return acc

            # TODO(deh): Wtf cases?
            elif decl.hdr.mode == TOK_BEFORE and \
                 decl.hdr.tac.startswith("<ssreflect_plugin::ssrtclseq@0>"):
                acc += [self.parse_ssrtclseq()]
            elif decl.hdr.mode == TOK_AFTER and \
                 decl.hdr.tac.startswith("<ssreflect_plugin::ssrtclseq@0>"):
                return acc

            # TODO(deh): Wtf cases??
            elif decl.hdr.mode == TOK_BEFORE and \
                 decl.hdr.tac.startswith("<ssreflect_plugin::ssrtcldo@0>"):
                acc += [self.parse_ssrtcldo()]

            # Variable-depth nested cases
            elif decl.hdr.mode == TOK_BEFORE:
                # apply
                # rewrite
                # simpl
                acc += [self.parse_generic()]
            else:
                self._mylog("Contents of accumulator before error")
                for tac in acc:
                    self._mylog(tac)
                raise NameError("Parsing error {}".format(decl))
        return acc


# TODO(deh): deprecate
"""
class AssumpTac(Tac):
    def __init__(self, uid, alias, core):
        assert isinstance(alias[0], TacStDecl)
        assert isinstance(alias[1], TacStDecl)
        assert isinstance(core, TacStDecl)

        super().__init__(uid)
        self.alias = alias
        self.core = core

    def has_subtac(self):
        return False

    def in_edge(self):
        return self.alias[0].hdr.gid

    def out_edges(self):
        return [self.alias[1].hdr.gid]

    def __str__(self):
        es = [str(self.alias[0]), str(self.alias[1]), str(self.core)]
        return "Assump({}; {})".format(self.uid, ", ".join(es))
"""

# TODO(deh): deprecate
"""
class ReflTac(Tac):
    def __init__(self, uid, alias, core):
        assert isinstance(alias[0], TacStDecl)
        assert isinstance(alias[1], TacStDecl)
        assert isinstance(core, TacStDecl)

        super().__init__(uid)
        self.alias = alias
        self.core = core

    def has_subtac(self):
        return False

    def in_edge(self):
        return self.alias[0].hdr.gid

    def out_edges(self):
        return [self.alias[1].hdr.gid]

    def __str__(self):
        es = [str(self.alias[0]), str(self.alias[1]), str(self.core)]
        return "Refl({}; {})".format(self.uid, ", ".join(es))
"""

# TODO(deh): deprecate
"""
def parse_assump(self):
    # before(assumption)
    # after(assumption)
    # before(assumption@0)
    # [after(assumption@0)]
    # Internal
    it = self.it
    self._mylog("@parse_assump:before<{}>".format(it.peek()))

    bf_assump = next(it)
    af_assump = next(it)
    bf_assump0 = next(it)
    if it.has_next() and \
       it.peek().hdr.tac.startswith("<coretactics::assumption@0>"):
        next(it)
    return AssumpTac(self._getuid(), (bf_assump, af_assump), bf_assump0)
"""

# TODO(deh): deprecate
"""
def parse_refl(self):
    # before(reflexivity)
    # after(reflexivity)
    # before(reflexivity@0)
    # [after(reflexivity@0)]
    # Internal
    it = self.it
    self._mylog("@parse_refl:before<{}>".format(it.peek()))

    bf_refl = next(it)
    af_refl = next(it)
    bf_refl0 = next(it)
    if it.has_next() and \
       it.peek().hdr.tac.startswith("<coretactics::reflexivity@0>"):
        next(it)
    return ReflTac(self._getuid(), (bf_refl, af_refl), bf_refl0)
"""

# TODO(deh): deprecate
"""
def parse_triv(self):
    # before(trivial)
    #   before(trivial@0)
    #   [after(trivial@0)]
    # [after(trivial)]
    # Internal
    it = self.it
    self._mylog("@parse_triv:before<{}>".format(it.peek()))

    bf_triv = next(it)
    bf_triv0 = next(it)
    if it.has_next() and \
       it.peek().hdr.tac.startswith("<g_auto::trivial@0>"):
        # af_triv0 = next(it)
        next(it)
        if it.has_next() and \
           it.peek().hdr.tac.startswith("trivial"):
            # af_triv = next(it)
            next(it)
    return TrivTac(self._getuid(), bf_triv, bf_triv0)
"""

"""
def parse_ssrby(self):
    # before(ssrby)
    #  before(ssrby@0)
    #    TacTree
    #  after(ssrby@0)
    # after(ssrby@0)
    # Internal
    it = self.it
    self._mylog("@parse_srrby:before<{}>".format(it.peek()))

    # Reconstruct Ssreflect by tactic
    bf_by = next(it)
    bf_by0 = next(it)
    return SsrbyTac(self._getuid(), bf_by, bf_by0)
"""

"""
def parse_ssrhave(self):
    # before(ssrhavefwdwbinders)
    #   before(ssrhave@0)
    #     TacTree
    #  after(ssrhave@0)
    # after(ssrhavefwdwbinders)
    # Internal
    it = self.it
    self._mylog("@parse_srrhave:before<{}>".format(it.peek()))

    # Reconstruct Ssreflect have tactic
    bf_havefwd = next(it)
    bf_have0 = next(it)
    self.depth += 1
    body = self.parse_tactree()
    self.depth -= 1
    af_have0 = next(it)
    af_havefwd = next(it)
    return SsrhaveTac(self._getuid(), (bf_havefwd, af_havefwd),
                      (bf_have0, af_have0), body)
"""

# TODO(deh): deprecated
"""
class TrivTac(Tac):
    def __init__(self, uid, alias, core):
        assert isinstance(alias, TacStDecl)
        assert isinstance(core, TacStDecl)

        super().__init__(uid)
        self.alias = alias
        self.core = core

    def has_subtac(self):
        return False

    def in_edge(self):
        return self.alias.hdr.gid

    def out_edges(self):
        return [self.core.hdr.gid]

    def __str__(self):
        es = [str(self.alias), str(self.core)]
        return "Trivial({}; {})".format(self.uid, ", ".join(es))
"""

# TODO(deh): deprecate
"""
class SsrbyTac(Tac):
    def __init__(self, uid, alias, core):
        assert isinstance(alias, TacStDecl)
        assert isinstance(core, TacStDecl)

        super().__init__(uid)
        self.alias = alias
        self.core = core

    def has_subtac(self):
        return False

    def in_edge(self):
        return self.alias.hdr.gid

    def out_edges(self):
        return [self.core.hdr.gid]

    def __str__(self):
        es = [str(self.alias), str(self.core)]
        return "Srrby({}; {})".format(self.uid, ", ".join(es))
"""

"""
class SsrapplyTac(Tac):
    def __init__(self, uid, bf_alias, bf_core, af_cores, af_aliases):
        assert isinstance(bf_alias, TacStDecl)
        assert isinstance(bf_core, TacStDecl)
        for after in af_cores:
            assert isinstance(after, TacStDecl)
        for after in af_aliases:
            assert isinstance(after, TacStDecl)

        super().__init__(uid)
        self.bf_alias = bf_alias
        self.bf_core = bf_core
        self.af_cores = af_cores
        self.af_aliases = af_aliases

    def has_subtac(self):
        return False

    def in_edge(self):
        return self.bf_alias.hdr.gid

    def out_edges(self):
        return [after.hdr.gid for after in self.af_aliases]

    def __str__(self):
        ps = ["({}, {})".format(self.bf_alias, after)
              for after in self.af_aliases]
        body1 = ", ".join([str(x) for x in self.af_cores])
        body2 = ", ".join([str(x) for x in self.af_aliases])
        return "Ssrapply({}; {}; {}; {})".format(self.uid, ", ".join(ps),
                                                 body1, body2)
"""

"""
class SsrrwTac(Tac):
    def __init__(self, uid, bf_alias, bf_core, af_cores, af_aliases, body):
        assert isinstance(bf_alias, TacStDecl)
        assert isinstance(bf_core, TacStDecl)
        for after in af_cores:
            assert isinstance(after, TacStDecl)
        for after in af_aliases:
            assert isinstance(after, TacStDecl)
        for tac in body:
            assert isinstance(tac, Tac)

        super().__init__(uid)
        self.bf_alias = bf_alias
        self.bf_core = bf_core
        self.af_cores = af_cores
        self.af_aliases = af_aliases
        self.body = body

    def has_subtac(self):
        return True

    def in_edge(self):
        return self.bf_alias.hdr.gid

    def out_edges(self):
        return [after.hdr.gid for after in self.af_aliases]

    def __str__(self):
        ps = ["({}, {})".format(self.bf_alias, after)
              for after in self.af_aliases]
        body = ", ".join([str(x) for x in self.body])
        return "Ssrrw({}; {}; {})".format(self.uid, ", ".join(ps), body)
"""

"""
class ExactTac(Tac):
    def __init__(self, uid, alias, core):
        assert isinstance(alias, TacStDecl)
        assert isinstance(core[0], TacStDecl)
        assert isinstance(core[1], TacStDecl)

        super().__init__(uid, True)
        self.alias = alias
        self.core = core

    def has_subtac(self):
        return False

    def in_edge(self):
        return self.alias.hdr.gid

    def out_edges(self):
        return [self.core[1].hdr.gid]

    def __str__(self):
        es = [str(self.alias), str(self.core[0]), str(self.core[1])]
        return "Exact({}; {})".format(self.uid, ", ".join(es))
"""

"""
def parse_ssrapply(self):
    # before(srrapply)
    #   before(ssrapply@0)
    #     TacTree
    #   after(ssrapply@0-1)
    #   ...
    #   after(ssrapply@0-n)
    # after(ssrapply-1)
    # ...
    # after(ssrapply-n)
    # Internal
    it = self.it
    self._mylog("@parse_ssrapply:before<{}>".format(it.peek()))

    # Reconstruct Ssreflect apply tactic
    bf_apply = next(it)
    bf_apply0 = next(it)
    body = self.parse_tactree()

    acc0 = []
    ngs = it.peek().hdr.ngs
    for _ in range(0, ngs - bf_apply0.hdr.ngs + 1):
        decl_p = next(it)
        acc0 += [decl_p]

    acc = []
    for _ in range(0, ngs - bf_apply.hdr.ngs + 1):
        decl_p = next(it)
        acc += [decl_p]
    return SsrapplyTac(self._getuid(), bf_apply, bf_apply0, acc0, acc, body)
"""

"""
def parse_exact(self):
    # before(exact)
    #   before(exact@0)
    #   after(exact@0)
    # Internal
    it = self.it
    self._mylog("@parse_exact:before<{}>".format(it.peek()))

    bf_exact = next(it)
    bf_exact0 = next(it)
    af_exact0 = next(it)
    return ExactTac(self._getuid(), bf_exact, (bf_exact0, af_exact0))
"""
