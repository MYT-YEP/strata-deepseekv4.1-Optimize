"""Check benchmark completeness and exercise generated Python in a narrow AST sandbox."""
import argparse
import ast
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(r"F:\STRATA\tuning\20tok-goal")
SAFE_BUILTINS = {k: getattr(__import__("builtins"), k) for k in
                 ("len", "set", "list", "tuple", "sorted", "enumerate", "range", "min", "max", "zip", "dict", "bool")}
SAFE_METHODS = {"append", "add", "extend", "sort", "copy", "pop"}
ALLOWED = {ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.Assign, ast.AugAssign,
           ast.For, ast.If, ast.Expr, ast.Pass, ast.Break, ast.Continue, ast.Name, ast.Load, ast.Store,
           ast.Constant, ast.List, ast.Tuple, ast.Set, ast.Dict, ast.Call, ast.Attribute, ast.Subscript,
           ast.Slice, ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod, ast.Compare, ast.Eq,
           ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot,
           ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.USub, ast.UAdd, ast.Not, ast.IfExp,
           ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.comprehension, ast.Lambda,
           ast.Starred, ast.keyword}


class StripAnnotations(ast.NodeTransformer):
    def visit_FunctionDef(self, node):
        node.decorator_list = []
        node.returns = None
        for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
            arg.annotation = None
        if node.args.vararg:
            node.args.vararg.annotation = None
        if node.args.kwarg:
            node.args.kwarg.annotation = None
        return self.generic_visit(node)

    def visit_AnnAssign(self, node):
        if node.value is None:
            return ast.copy_location(ast.Pass(), node)
        return ast.copy_location(ast.Assign(targets=[node.target], value=self.visit(node.value)), node)


def fenced(answer):
    if "```python" in answer:
        return answer.split("```python", 1)[1].split("```", 1)[0]
    if "```" in answer:
        return answer.split("```", 1)[1].split("```", 1)[0]
    return answer


def worker(case, answer):
    name = {"python_unique": "stable_unique", "python_intervals": "merge_intervals"}[case]
    tree = ast.parse(fenced(answer))
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(functions) != 1:
        raise ValueError("Expected function was not found exactly once")
    fn = StripAnnotations().visit(functions[0])
    if fn.args.defaults or any(x is not None for x in fn.args.kw_defaults):
        raise ValueError("Functions with defaults are not executed by this checker")
    module = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    for n in ast.walk(module):
        if type(n) not in ALLOWED:
            raise ValueError("Unsupported syntax: " + type(n).__name__)
        if isinstance(n, ast.Name) and n.id.startswith("_"):
            raise ValueError("Private names are not allowed")
        if isinstance(n, ast.Attribute) and (n.attr not in SAFE_METHODS or not isinstance(n.value, ast.Name)):
            raise ValueError("Unsupported attribute access")
        if isinstance(n, ast.Call):
            if isinstance(n.func, ast.Name) and n.func.id not in SAFE_BUILTINS:
                raise ValueError("Unsupported function call: " + n.func.id)
            if not isinstance(n.func, (ast.Name, ast.Attribute)):
                raise ValueError("Unsupported call target")
        if isinstance(n, ast.FunctionDef) and n is not fn:
            raise ValueError("Nested functions are not executed")
    namespace = {"__builtins__": SAFE_BUILTINS}
    exec(compile(module, "<generated-function>", "exec"), namespace)
    f = namespace[name]
    if case == "python_unique":
        cases = [([], []), ([2, 2, 1, 2], [2, 1]), (["a", "b", "a"], ["a", "b"]),
                 ([-1, 0, -1, 2], [-1, 0, 2]), ([3, 1, 2, 3], [3, 1, 2]), ([1, True, 1], [1])]
        for items, expected in cases:
            before = list(items)
            assert f(items) == expected and items == before
    else:
        cases = [([], []), ([(1, 3), (2, 6)], [(1, 6)]), ([(2, 4), (1, 2)], [(1, 4)]),
                 ([(1, 10), (3, 4)], [(1, 10)]), ([(-3, -1), (-1, 0), (2, 4)], [(-3, 0), (2, 4)]),
                 ([(8, 9), (1, 2), (2, 3)], [(1, 3), (8, 9)])]
        for items, expected in cases:
            before = list(items)
            actual = f(items)
            assert [tuple(x) for x in actual] == expected and items == before
    return {"status": "passed", "tests": len(cases), "input_unchanged": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--result", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    if args.worker:
        data = json.load(sys.stdin)
        try:
            print(json.dumps(worker(data["case"], data["answer"])))
        except Exception as exc:
            print(json.dumps({"status": "not_passed", "reason": str(exc)}))
        return 0
    if not args.result or not args.output:
        parser.error("--result and --output are required")
    if args.result.resolve().parent != ROOT.resolve() or args.output.resolve().parent != ROOT.resolve():
        parser.error("Both paths must be in the tuning directory")
    if args.output.exists():
        raise SystemExit("Refusing to overwrite an existing quality report")
    data = json.loads(args.result.read_text(encoding="utf-8"))
    checked = []
    for row in data.get("cases", []):
        record = {"name": row.get("name"), "answer_nonempty": bool(row.get("answer", "").strip()),
                  "finished_normally": row.get("finish_reason") == "stop"}
        if row.get("name") in ("python_unique", "python_intervals"):
            try:
                proc = subprocess.run([sys.executable, "-I", "-X", "utf8", str(pathlib.Path(__file__).resolve()),
                                       "--worker"], input=json.dumps({"case": row["name"], "answer": row["answer"]}),
                                      text=True, capture_output=True, timeout=10,
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                record["code_check"] = json.loads(proc.stdout) if proc.returncode == 0 else {"status": "worker_failed"}
            except subprocess.TimeoutExpired:
                record["code_check"] = {"status": "timed_out"}
        checked.append(record)
    result = {"source": str(args.result), "cases": checked,
              "complete_run": bool(data.get("summary")) and not data.get("error"),
              "note": "Short functional checks, not a comprehensive quality evaluation."}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
