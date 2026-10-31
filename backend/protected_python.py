"""A deliberately small Python subset for calculations and public workspace files.

This evaluator does not accept arbitrary Python programs. It validates the AST,
exposes only named operations, and runs in a separate, resource-limited process.
"""
import ast
import json
import math
import resource
import sys
from pathlib import Path
from types import SimpleNamespace

BASE=Path.cwd().resolve()

class WorkspacePath:
    def __init__(self, path):
        self._path=(BASE/str(path)).resolve()
        if not self._path.is_relative_to(BASE):
            raise ValueError('Files must remain in the public workspace')
    def read_text(self):
        if self._path.stat().st_size>65536:raise ValueError('File too large')
        return self._path.read_text()
    def write_text(self, value):
        if not isinstance(value,str) or len(value.encode())>65536:raise ValueError('Write at most 64 KiB of text')
        return self._path.write_text(value)
    def exists(self):return self._path.exists()


def main():
    resource.setrlimit(resource.RLIMIT_CPU,(2,2))
    try:
        resource.setrlimit(resource.RLIMIT_AS,(128*1024*1024,128*1024*1024))
    except ValueError:
        # macOS refuses any memory cap below its shared-cache mapping; the CPU cap still bounds native runs.
        if sys.platform!='darwin':raise
    resource.setrlimit(resource.RLIMIT_FSIZE,(65536,65536))
    tree=ast.parse(sys.argv[1])
    math_functions={key:getattr(math,key) for key in ('sqrt','sin','cos','tan','floor','ceil','log','log10','exp','fabs','pi','e')}
    modules={'math':SimpleNamespace(**math_functions),'json':SimpleNamespace(loads=json.loads,dumps=json.dumps),'pathlib':SimpleNamespace(Path=WorkspacePath)}
    attributes=set(math_functions)|{'loads','dumps','Path','read_text','write_text','exists'}
    nodes=(ast.Module,ast.Import,ast.ImportFrom,ast.alias,ast.Expr,ast.Assign,ast.AugAssign,ast.Name,ast.Load,ast.Store,ast.Constant,ast.Call,ast.keyword,ast.Attribute,ast.BinOp,ast.UnaryOp,ast.BoolOp,ast.Compare,ast.List,ast.Tuple,ast.Dict,ast.Set,ast.Subscript,ast.Slice,ast.If,ast.For,ast.IfExp,ast.JoinedStr,ast.FormattedValue,ast.operator,ast.unaryop,ast.boolop,ast.cmpop)
    for node in ast.walk(tree):
        if not isinstance(node,nodes):raise ValueError(f'Unsupported Python syntax: {type(node).__name__}')
        if isinstance(node,ast.Name) and node.id.startswith('_'):raise ValueError('Private names are not allowed')
        if isinstance(node,ast.Attribute) and node.attr not in attributes:raise ValueError('Unsupported attribute')
        if isinstance(node,(ast.Import,ast.ImportFrom)):
            imports=[item.name for item in node.names] if isinstance(node,ast.Import) else [node.module]
            if any(name not in modules for name in imports) or (isinstance(node,ast.ImportFrom) and node.level):raise ValueError('Only math, json, and pathlib imports are supported')
            if any(item.asname and item.asname.startswith('_') or item.name.startswith('_') for item in node.names):raise ValueError('Private imports are not allowed')
    def limited_import(name,globals=None,locals=None,fromlist=(),level=0):
        if name not in modules or level:raise ImportError('Unsupported module')
        return modules[name]
    builtins={'print':print,'range':range,'len':len,'sum':sum,'min':min,'max':max,'abs':abs,'round':round,'sorted':sorted,'enumerate':enumerate,'str':str,'int':int,'float':float,'bool':bool,'list':list,'dict':dict,'tuple':tuple,'zip':zip,'__import__':limited_import}
    scope={'__builtins__':builtins,'Path':WorkspacePath,'read_text':lambda path:WorkspacePath(path).read_text(),'write_text':lambda path,text:WorkspacePath(path).write_text(text)}
    exec(compile(tree,'<protected-python>','exec'),scope,scope)

if __name__=='__main__':
    main()
