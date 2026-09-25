"""Tests for scripts/ccfind. Every fixture is synthetic JSONL written here; no real transcripts.

Run: python3 -m unittest discover -s tests -v
"""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import plistlib
import shlex
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "ccfind")


def load():
    loader = importlib.machinery.SourceFileLoader("ccfind", SCRIPT)
    spec = importlib.util.spec_from_loader("ccfind", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


cc = load()
TS = "2026-09-20T10:00:%02d.000Z"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "projects")
        os.makedirs(self.root)
        self.env = {k: os.environ.get(k) for k in ("CCFIND_ROOT", "CCFIND_DB", "CCFIND_PRICES")}
        os.environ["CCFIND_ROOT"] = self.root
        os.environ["CCFIND_DB"] = os.path.join(self.tmp.name, "cache", "index.db")
        os.environ["CCFIND_PRICES"] = os.path.join(self.tmp.name, "prices.json")
        self.con = None
        self.n = 0

    def tearDown(self):
        if self.con:
            self.con.close()
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    # -- fixture helpers
    def ts(self):
        self.n += 1
        return TS % (self.n % 60)

    def path(self, sid, cwd="/w/proj", agent=None):
        d = os.path.join(self.root, cc.encode_dir(cwd))
        if agent:
            d = os.path.join(d, sid, "subagents")
            os.makedirs(d, exist_ok=True)
            return os.path.join(d, agent + ".jsonl")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, sid + ".jsonl")

    def write(self, path, recs, mode="w"):
        with open(path, mode) as f:
            for r in recs:
                f.write(json.dumps(r) + "\n")

    def user(self, sid, content, cwd="/w/proj", **kw):
        r = {"type": "user", "sessionId": sid, "cwd": cwd, "gitBranch": "main", "timestamp": self.ts(),
             "message": {"role": "user", "content": content}}
        r.update(kw)
        return r

    def asst(self, sid, blocks, mid=None, usage=None, model="claude-test", cwd="/w/proj"):
        m = {"role": "assistant", "content": blocks, "model": model, "id": mid or "m%d" % self.n}
        if usage:
            m["usage"] = usage
        return {"type": "assistant", "sessionId": sid, "cwd": cwd, "gitBranch": "main", "timestamp": self.ts(),
                "message": m}

    def index(self):
        if self.con is None:
            self.con = cc.connect()
        return cc.index_all(self.con)

    def ids(self, *terms, **kw):
        return [r["id"] for r in cc.search(self.con, list(terms), **kw)]

    def run_main(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cc.main(argv)
        return code, buf.getvalue()


class Extraction(Base):
    def test_string_and_block_content(self):
        self.write(self.path("s1"), [self.user("s1", "alpha one"),
                                     self.user("s1", [{"type": "text", "text": "bravo two"}])])
        self.index()
        self.assertEqual(self.ids("alpha"), ["s1"])
        self.assertEqual(self.ids("bravo"), ["s1"])

    def test_tool_result_only_user_records_skipped(self):
        self.write(self.path("s1"), [self.user("s1", "hello there"), self.user(
            "s1", [{"type": "tool_result", "tool_use_id": "t1", "content": "zulu secret"}])])
        self.index()
        self.assertEqual(self.ids("zulu"), [])

    def test_meta_and_injected_text_skipped(self):
        self.write(self.path("s1"), [
            self.user("s1", "hello"),
            self.user("s1", [{"type": "text", "text": "metaword skill body"}], isMeta=True),
            self.user("s1", "<task-notification>notifword</task-notification>"),
            self.user("s1", "[Request interrupted by user] interruptword"),
            self.user("s1", "summaryword", isCompactSummary=True),
        ])
        self.index()
        for w in ("metaword", "notifword", "interruptword", "summaryword"):
            self.assertEqual(self.ids(w), [], w)

    def test_command_args_extracted(self):
        self.write(self.path("s1"), [self.user(
            "s1", "<command-message>harden-plan</command-message>\n<command-name>/harden-plan</command-name>\n"
                  "<command-args>quokka review</command-args>")])
        self.index()
        self.assertEqual(self.ids("quokka"), ["s1"])
        names = [r[0] for r in self.con.execute("SELECT name FROM events WHERE kind='command'")]
        self.assertEqual(names, ["harden-plan"])

    def test_queued_command_indexed(self):
        self.write(self.path("s1"), [self.user("s1", "first"), {
            "type": "attachment", "sessionId": "s1", "timestamp": self.ts(),
            "attachment": {"type": "queued_command", "prompt": "wombat please", "commandMode": "prompt",
                           "origin": {"kind": "human"}}}, {
            "type": "attachment", "sessionId": "s1", "timestamp": self.ts(),
            "attachment": {"type": "queued_command", "prompt": "peerword", "commandMode": "prompt",
                           "origin": {"kind": "peer"}}}])
        self.index()
        self.assertEqual(self.ids("wombat"), ["s1"])
        self.assertEqual(self.ids("peerword"), [])
        q = self.con.execute("SELECT sum(queued) FROM prompts WHERE role='user'").fetchone()[0]
        self.assertEqual(q, 1)

    def test_thinking_skipped(self):
        self.write(self.path("s1"), [self.user("s1", "hi"), self.asst(
            "s1", [{"type": "thinking", "thinking": "narwhal"}, {"type": "text", "text": "visible reply"}])])
        self.index()
        self.assertEqual(self.ids("narwhal"), [])
        self.assertEqual(self.ids("visible"), ["s1"])

    def test_custom_title_beats_ai_title_and_meta_row_replaced(self):
        p = self.path("s1")
        self.write(p, [self.user("s1", "hi"), {"type": "ai-title", "aiTitle": "Oldname Title", "sessionId": "s1"}])
        self.index()
        self.assertEqual(self.ids("oldname"), ["s1"])
        self.write(p, [{"type": "custom-title", "customTitle": "Customname", "sessionId": "s1"},
                       {"type": "ai-title", "aiTitle": "Newer Ai", "sessionId": "s1"}], mode="a")
        self.index()
        self.assertEqual(self.ids("customname"), ["s1"])
        self.assertEqual(self.ids("oldname"), [])
        n = self.con.execute("SELECT count(*) FROM docs WHERE session_id='s1' AND role='meta'").fetchone()[0]
        self.assertEqual(n, 1)
        res = cc.search(self.con, ["customname"])
        self.assertEqual(res[0]["title"], "Customname")


class Incremental(Base):
    def test_partial_trailing_line_waits_for_newline(self):
        p = self.path("s1")
        whole = json.dumps(self.user("s1", "complete line")) + "\n"
        part = json.dumps(self.user("s1", "pangolin arrives"))
        with open(p, "w") as f:
            f.write(whole + part[:30])
        self.index()
        self.assertEqual(self.ids("pangolin"), [])
        with open(p, "a") as f:
            f.write(part[30:] + "\n")
        self.index()
        self.assertEqual(self.ids("pangolin"), ["s1"])

    def test_truncated_file_reindexed(self):
        p = self.path("s1")
        self.write(p, [self.user("s1", "keepword"), self.user("s1", "dropword " * 20)])
        self.index()
        self.write(p, [self.user("s1", "keepword")])
        c = self.index()
        self.assertEqual(c["reset"], 1)
        self.assertEqual(self.ids("dropword"), [])
        self.assertEqual(self.ids("keepword"), ["s1"])

    def test_same_size_new_head_reindexed(self):
        p = self.path("s1")
        self.write(p, [self.user("s1", "aaaaaaaa")])
        self.index()
        size = os.path.getsize(p)
        self.write(p, [self.user("s1", "bbbbbbbb")])
        self.assertEqual(os.path.getsize(p), size)
        self.index()
        self.assertEqual(self.ids("aaaaaaaa"), [])
        self.assertEqual(self.ids("bbbbbbbb"), ["s1"])

    def test_subagent_change_keeps_parent_rows(self):
        self.write(self.path("s1"), [self.user("s1", "parentword")])
        ap = self.path("s1", agent="agent-1")
        self.write(ap, [self.asst("s1", [{"type": "text", "text": "childword"}])])
        self.index()
        self.write(ap, [self.asst("s1", [{"type": "text", "text": "laterword"}])], mode="a")
        self.index()
        self.assertEqual(self.ids("parentword"), ["s1"])
        self.assertEqual(self.ids("childword"), ["s1"])
        self.assertEqual(self.ids("laterword"), ["s1"])
        self.assertEqual(self.ids("childword", no_agents=True), [])

    def test_deleted_file_pruned(self):
        self.write(self.path("s1"), [self.user("s1", "stays")])
        p2 = self.path("s2")
        self.write(p2, [self.user("s2", "vanishes")])
        self.index()
        self.assertEqual(self.ids("vanishes"), ["s2"])
        os.remove(p2)
        c = self.index()
        self.assertEqual(c["pruned"], 1)
        self.assertEqual(self.ids("vanishes"), [])
        self.assertIsNone(self.con.execute("SELECT 1 FROM sessions WHERE id='s2'").fetchone())

    def test_cwd_resolution(self):
        self.write(self.path("s1", cwd="/w/proj"), [self.user("s1", "one", cwd="/w/proj/sub"),
                                                    self.user("s1", "two", cwd="/w/proj"),
                                                    self.user("s1", "three", cwd="/w/elsewhere")])
        self.write(self.path("s2", cwd="/w/proj/.claude/worktrees/x"), [
            self.user("s2", "hi", cwd="/w/proj"),
            {"type": "relocated", "sessionId": "s2", "relocatedCwd": "/w/proj/.claude/worktrees/x"}])
        self.index()
        rows = dict(self.con.execute("SELECT id, cwd FROM sessions"))
        self.assertEqual(rows["s1"], "/w/proj")
        self.assertEqual(rows["s2"], "/w/proj/.claude/worktrees/x")

    def test_mode_switch_rebuilds(self):
        self.write(self.path("s1"), [self.user("s1", "hi"), self.asst(
            "s1", [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "pelican --run"}}])])
        self.index()
        self.assertEqual(self.ids("pelican"), [])
        self.con.close()
        self.con = None
        with contextlib.redirect_stdout(io.StringIO()):
            cc.main(["index", "--mode", "deep"])
        self.con = cc.connect()
        self.assertEqual(cc.get_mode(self.con), "deep")
        self.assertEqual(self.ids("pelican"), ["s1"])


class Search(Base):
    def test_session_level_and(self):
        self.write(self.path("s1"), [self.user("s1", "kiwi first"), self.user("s1", "mango second")])
        self.write(self.path("s2"), [self.user("s2", "kiwi only")])
        self.index()
        self.assertEqual(self.ids("kiwi", "mango"), ["s1"])
        self.assertEqual(sorted(self.ids("kiwi", "mango", any_=True)), ["s1", "s2"])

    def test_query_quoting(self):
        self.write(self.path("s1"), [self.user("s1", "edit x.json and a-b then foo:bar")])
        self.index()
        self.assertEqual(self.ids("x.json"), ["s1"])
        self.assertEqual(self.ids("a-b"), ["s1"])
        self.assertEqual(self.ids("foo:bar"), ["s1"])
        self.assertEqual(self.ids('"'), [])
        self.assertEqual(self.ids('fo"o'), [])
        self.assertEqual(self.ids("ed*"), ["s1"])

    def test_open_shell_quotes_cwd(self):
        cwd = os.path.join(self.tmp.name, "it's here")
        os.makedirs(cwd)
        self.write(self.path("abc123", cwd=cwd), [self.user("abc123", "hello", cwd=cwd)])
        self.index()
        code, out = self.run_main(["open", "abc1"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "cd %s && claude --resume abc123" % shlex.quote(cwd))

    def test_open_by_rank_and_refuses_x_inside_claude(self):
        self.write(self.path("s1"), [self.user("s1", "rankword")])
        self.index()
        self.run_main(["rankword"])
        old = os.environ.get("CLAUDECODE")
        os.environ["CLAUDECODE"] = "1"
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                code, out = self.run_main(["open", "1", "-x"])
        finally:
            if old is None:
                os.environ.pop("CLAUDECODE")
            else:
                os.environ["CLAUDECODE"] = old
        self.assertEqual(code, 3)
        self.assertIn("claude --resume s1", out)


class Stats(Base):
    def stats(self, **kw):
        self.index()
        return cc.compute_stats(self.con, **kw)

    def test_usage_dedup_and_synthetic_skipped(self):
        u = lambda o: {"input_tokens": 1, "output_tokens": o, "cache_creation_input_tokens": 2,
                       "cache_read_input_tokens": 3}
        self.write(self.path("s1"), [
            self.user("s1", "hi"),
            self.asst("s1", [{"type": "text", "text": "a"}], mid="M1", usage=u(5)),
            self.asst("s1", [{"type": "text", "text": "b"}], mid="M1", usage=u(10)),
            self.asst("s1", [{"type": "text", "text": "c"}], mid="M1", usage=u(7)),
            self.asst("s1", [{"type": "text", "text": "API Error: nope"}], mid="M2", usage=u(99),
                      model="<synthetic>"),
        ])
        t = self.stats()["tokens"]
        self.assertEqual(t["total"]["output"], 10)
        self.assertEqual([m["model"] for m in t["by_model"]], ["claude-test"])

    def test_edit_lines_and_rejected(self):
        self.write(self.path("s1"), [
            self.user("s1", "hi"),
            self.asst("s1", [
                {"type": "tool_use", "id": "e1", "name": "Edit",
                 "input": {"file_path": "/a.py", "old_string": "c", "new_string": "a\nb"}},
                {"type": "tool_use", "id": "e2", "name": "Write", "input": {"file_path": "/b.py", "content": "x\ny\nz"}},
                {"type": "tool_use", "id": "e3", "name": "MultiEdit", "input": {"file_path": "/c.py", "edits": [
                    {"old_string": "1\n2", "new_string": "3"}, {"old_string": "4", "new_string": "5\n6"}]}},
                {"type": "tool_use", "id": "e4", "name": "Edit",
                 "input": {"file_path": "/d.py", "old_string": "q", "new_string": "r\ns\nt\nu"}},
            ]),
            self.user("s1", [{"type": "tool_result", "tool_use_id": "e4", "is_error": True, "content": "rejected"}]),
        ])
        cl = self.stats()["code_lines"]
        self.assertEqual(cl["added"], 2 + 3 + 3)
        self.assertEqual(cl["removed"], 1 + 0 + 3)
        self.assertEqual(cl["rejected_or_failed_edits"], 1)

    def test_word_cleaning_and_once_per_message(self):
        self.write(self.path("s1"), [self.user(
            "s1", "giraffe giraffe the <pasted_content id=1>rowrow rowrow</pasted_content id=1> "
                  "```\ncodeword\n``` see https://example.com/pathword [Image #1] and /usr/lib/filepathword\n"
                  "➜ repo git:(main) terminalword")])
        w = {x["word"]: x for x in self.stats()["your_words"]["words"]}
        self.assertEqual(w["giraffe"]["messages"], 1)
        for banned in ("the", "rowrow", "codeword", "pathword", "image", "https", "filepathword", "terminalword"):
            self.assertNotIn(banned, w)

    def test_openers(self):
        self.write(self.path("s1"), [self.user("s1", "proceed now"), self.user("s1", "Proceed now please"),
                                     self.user("s1", "why is it slow")])
        o = {x["opener"]: x["count"] for x in self.stats()["your_words"]["openers"]}
        self.assertEqual(o["proceed now"], 2)
        self.assertEqual(o["why is"], 1)

    def test_template_threshold(self):
        for i in range(3):
            sid = "t%d" % i
            recs = [self.user(sid, "alpha bravo charlie delta echo extra%d" % i)]
            if i < 2:
                recs.append(self.user(sid, "foxtrot golf hotel india juliet"))
            self.write(self.path(sid), recs)
        phrases = [t["phrase"] for t in self.stats()["your_words"]["templates"]]
        self.assertIn("alpha bravo charlie delta echo", phrases)
        self.assertFalse(any("foxtrot" in p for p in phrases))

    def test_project_and_since_filters(self):
        self.write(self.path("a1", cwd="/w/apple"), [self.user("a1", "old apple", cwd="/w/apple",
                                                               timestamp="2020-01-01T00:00:00.000Z")])
        self.write(self.path("b1", cwd="/w/banana"), [self.user("b1", "new banana", cwd="/w/banana")])
        self.assertEqual(self.stats(project="apple")["overview"]["prompts"], 1)
        s = self.stats(since="2026-01-01")
        self.assertEqual(s["overview"]["prompts"], 1)
        self.assertEqual(s["overview"]["sessions"], 1)

    def test_cost_only_with_prices_file(self):
        self.write(self.path("s1"), [self.user("s1", "hi"), self.asst(
            "s1", [{"type": "text", "text": "ok"}], mid="M1",
            usage={"input_tokens": 1000000, "output_tokens": 2000000, "cache_creation_input_tokens": 0,
                   "cache_read_input_tokens": 0})])
        t = self.stats()["tokens"]
        self.assertFalse(t["has_prices"])
        self.assertNotIn("cost", t["by_model"][0])
        with open(os.environ["CCFIND_PRICES"], "w") as f:
            json.dump({"claude-test": {"input": 1, "output": 5, "cache_write": 0, "cache_read": 0}}, f)
        t = cc.compute_stats(self.con)["tokens"]
        self.assertTrue(t["has_prices"])
        self.assertEqual(t["by_model"][0]["cost"], 11.0)

    def test_html_is_self_contained(self):
        self.write(self.path("s1"), [self.user("s1", "hello world"),
                                     self.asst("s1", [{"type": "text", "text": "hi"}])])
        out = cc.render_html(self.stats())
        self.assertNotRegex(out, r"<script[^>]+src=|<link[^>]+href=.https?:|@import")
        self.assertIn("<svg", out)
        self.assertIn("prefers-color-scheme", out)


class Typos(Base):
    def setUp(self):
        super().setUp()
        self.write(self.path("common"), [self.user("common", "compare the fares, message %d" % i)
                                         for i in range(25)] + [self.user("common", "ride fares")])
        self.write(self.path("typo"), [self.user("typo", "please comapre these")])
        self.write(self.path("other"), [self.user("other", "unrelated words only")])
        self.index()

    def test_osa_distance(self):
        self.assertEqual(cc.osa_distance("comapr", "compar", 2), 1)  # one adjacent swap
        self.assertEqual(cc.osa_distance("kitten", "sitting", 3), 3)
        self.assertEqual(cc.osa_distance("abc", "xyzabc", 1), 2)  # capped at limit + 1

    def test_rare_word_also_matches_common_spelling(self):
        notes = []
        self.assertEqual(sorted(r["id"] for r in cc.search(self.con, ["comapre"], notes=notes)),
                         ["common", "typo"])
        self.assertTrue(any("comapre" in n for n in notes))
        self.assertEqual(self.ids("fares", "comapre"), ["common"])

    def test_exact_turns_it_off(self):
        self.assertEqual(self.ids("comapre", exact=True), ["typo"])

    def test_common_words_are_not_corrected(self):
        notes = []
        cc.search(self.con, ["compare"], notes=notes)
        self.assertEqual(notes, [])

    def test_hyphenated_term_without_phrase_hits_is_split(self):
        notes = []
        ids = [r["id"] for r in cc.search(self.con, ["ride-comapre"], notes=notes)]
        self.assertEqual(ids, ["common"])
        self.assertTrue(any("phrase" in n for n in notes))


class Scope(Base):
    def test_headless_and_tmp_hidden_by_default(self):
        self.write(self.path("vis"), [self.user("vis", "zebrafish here")])
        self.write(self.path("hl"), [self.user("hl", "zebrafish headless", entrypoint="sdk-cli")])
        self.write(self.path("tp", cwd="/tmp/x"), [self.user("tp", "zebrafish scratch", cwd="/tmp/x")])
        self.index()
        self.assertEqual(self.ids("zebrafish"), ["vis"])
        self.assertEqual(sorted(self.ids("zebrafish", include_tmp=True)), ["hl", "tp", "vis"])
        self.assertEqual(cc.compute_stats(self.con)["overview"]["sessions"], 1)
        self.assertEqual(cc.compute_stats(self.con, include_tmp=True)["overview"]["sessions"], 3)
        ep = dict(self.con.execute("SELECT id, entrypoint FROM sessions"))
        self.assertEqual(ep["hl"], "sdk-cli")


class PasteFilter(Base):
    def test_raw_lines_counts_non_empty_lines(self):
        self.write(self.path("s1"), [self.user("s1", "one\n\ntwo\n   \nthree")])
        self.index()
        self.assertEqual(self.con.execute("SELECT raw_lines FROM prompts WHERE role='user'").fetchone()[0], 3)

    def test_pastes_left_out_of_word_bank(self):
        paste = "\n".join("kestrel falcon osprey harrier merlin line%d" % i for i in range(7))
        for i in range(3):
            sid = "p%d" % i
            self.write(self.path(sid), [self.user(sid, paste)])
        self.index()
        s = cc.compute_stats(self.con)
        self.assertFalse(any("kestrel" in t["phrase"] for t in s["your_words"]["templates"]))
        self.assertEqual(s["your_words"]["paste_like_excluded"], 3)
        s0 = cc.compute_stats(self.con, max_prompt_lines=0)
        self.assertTrue(any("kestrel" in t["phrase"] for t in s0["your_words"]["templates"]))
        self.assertEqual(s0["your_words"]["paste_like_excluded"], 0)


class Agent(Base):
    def setUp(self):
        super().setUp()
        self.la = os.path.join(self.tmp.name, "LaunchAgents")
        self.saved = {k: os.environ.get(k) for k in ("CCFIND_LAUNCH_AGENTS_DIR", "CCFIND_LAUNCHCTL")}
        os.environ["CCFIND_LAUNCH_AGENTS_DIR"] = self.la
        os.environ["CCFIND_LAUNCHCTL"] = shutil.which("true")
        self.platform = sys.platform

    def tearDown(self):
        sys.platform = self.platform
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()

    def quiet(self, argv):
        with contextlib.redirect_stderr(io.StringIO()):
            return self.run_main(argv)

    def test_plist_round_trip(self):
        pl = cc.agent_plist(600, "/py", "/s/ccfind", {"CCFIND_DB": "/d/i.db", "HOME": "/h", "CCFIND_ROOT": ""})
        back = plistlib.loads(plistlib.dumps(pl))
        self.assertEqual(back["Label"], "com.clumsyknight.ccfind")
        self.assertEqual(back["ProgramArguments"], ["/py", "/s/ccfind", "index", "--agent"])
        self.assertEqual(back["StartInterval"], 600)
        self.assertTrue(back["RunAtLoad"])
        self.assertTrue(back["LowPriorityIO"])
        self.assertEqual(back["ProcessType"], "Background")
        self.assertEqual(back["Nice"], 10)
        self.assertEqual(back["EnvironmentVariables"], {"CCFIND_DB": "/d/i.db"})
        self.assertEqual(back["StandardErrorPath"], os.path.join(os.path.dirname(cc.db_path()), "agent.log"))

    def test_install_and_uninstall(self):
        sys.platform = "darwin"
        # the fake launchctl always "finds" the old job, so install waits out its 5 s drain timeout
        code, out = self.quiet(["agent", "install", "--interval", "600"])
        self.assertEqual(code, 0, out)
        plist = os.path.join(self.la, "com.clumsyknight.ccfind.plist")
        self.assertTrue(os.path.exists(plist))
        code, out = self.quiet(["agent", "uninstall"])
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(plist))

    def test_interval_minimum_and_non_mac(self):
        sys.platform = "darwin"
        self.assertEqual(self.quiet(["agent", "install", "--interval", "60"])[0], 2)
        sys.platform = "linux"
        self.assertEqual(self.quiet(["agent", "status"])[0], 2)

    def test_status_does_not_create_db(self):
        sys.platform = "darwin"
        code, out = self.quiet(["agent", "status"])
        self.assertEqual(code, 0)
        self.assertIn("installed no", out)
        self.assertFalse(os.path.exists(cc.db_path()))


class Locking(Base):
    def test_busy_lock_skips_auto_index(self):
        self.write(self.path("s1"), [self.user("s1", "heron first")])
        self.index()
        self.write(self.path("s1"), [self.user("s1", "ibis later")], mode="a")
        with cc.index_lock(True, 1) as got:
            self.assertTrue(got)
            with cc.index_lock(True, 0.3) as got2:
                self.assertFalse(got2)
            code, out = self.run_main(["heron"])
            self.assertIn("s1", out)
            code, out = self.run_main(["ibis"])
            self.assertIn("no matches", out)  # not indexed: another indexer holds the lock
            self.assertEqual(self.run_main(["index", "--agent"])[0], 0)
        code, out = self.run_main(["ibis"])
        self.assertIn("s1", out)

    def test_old_schema_rebuilt_newer_refused(self):
        self.write(self.path("s1"), [self.user("s1", "hello")])
        self.index()
        self.con.execute("UPDATE meta SET value='2' WHERE key='schema_version'")
        self.con.close()
        self.con = cc.connect()
        self.assertEqual(self.con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0],
                         cc.SCHEMA_VERSION)
        self.con.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
        self.con.close()
        self.con = None
        st = os.stat(cc.db_path())
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as e:
                cc.connect()
        self.assertEqual(e.exception.code, 5)
        st2 = os.stat(cc.db_path())
        self.assertEqual((st.st_size, st.st_mtime), (st2.st_size, st2.st_mtime))


if __name__ == "__main__":
    unittest.main()
