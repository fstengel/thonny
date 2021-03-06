# -*- coding: utf-8 -*-

import ast
import sys
import logging

def extract_text_range(source, text_range):
    if isinstance(source, bytes):
        # TODO: may be wrong encoding
        source = source.decode("utf-8")

    lines = source.splitlines(True)
    # get relevant lines
    lines = lines[text_range.lineno - 1 : text_range.end_lineno]

    # trim last and first lines
    lines[-1] = lines[-1][: text_range.end_col_offset]
    lines[0] = lines[0][text_range.col_offset :]
    return "".join(lines)


def find_expression(node, text_range):
    for node in ast.walk(node):
        if (
            isinstance(node, ast.expr)
            and node.lineno == text_range.lineno
            and node.col_offset == text_range.col_offset
            and node.end_lineno == text_range.end_lineno
            and node.end_col_offset == text_range.end_col_offset
        ):
            return node


def parse_source(source: bytes, filename="<unknown>", mode="exec"):
    root = ast.parse(source, filename, mode)
    mark_text_ranges(root, source)
    return root


def get_last_child(node, skip_incorrect=True):
    def ok_node(node):
        if node is None:
            return None

        if skip_incorrect and getattr(node, "incorrect_range", False):
            return None

        return node

    def last_ok(nodes):
        for i in range(len(nodes) - 1, -1, -1):
            if ok_node(nodes[i]):
                node = nodes[i]
                if isinstance(node, ast.Starred):
                    if ok_node(node.value):
                        return node.value
                    else:
                        return None
                else:
                    return nodes[i]

        return None

    if isinstance(node, ast.Call):
        # TODO: take care of Python 3.5 updates (Starred etc.)
        if hasattr(node, "kwargs") and ok_node(node.kwargs):
            return node.kwargs
        elif hasattr(node, "starargs") and ok_node(node.starargs):
            return node.starargs
        else:
            kw_values = list(map(lambda x: x.value, node.keywords))
            last_ok_kw = last_ok(kw_values)
            if last_ok_kw:
                return last_ok_kw
            elif last_ok(node.args):
                return last_ok(node.args)
            else:
                return ok_node(node.func)

    elif isinstance(node, ast.BoolOp):
        return last_ok(node.values)

    elif isinstance(node, ast.BinOp):
        if ok_node(node.right):
            return node.right
        else:
            return ok_node(node.left)

    elif isinstance(node, ast.Compare):
        return last_ok(node.comparators)

    elif isinstance(node, ast.UnaryOp):
        return ok_node(node.operand)

    elif isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return last_ok(node.elts)

    elif isinstance(node, ast.Dict):
        # TODO: actually should pairwise check last value, then last key, etc.
        return last_ok(node.values)

    elif isinstance(
        node, (ast.Return, ast.Assign, ast.AugAssign, ast.Yield, ast.YieldFrom)
    ):
        return ok_node(node.value)

    elif isinstance(node, ast.Delete):
        return last_ok(node.targets)

    elif isinstance(node, ast.Expr):
        return ok_node(node.value)

    elif isinstance(node, ast.Assert):
        if ok_node(node.msg):
            return node.msg
        else:
            return ok_node(node.test)

    elif isinstance(node, ast.Subscript):
        if hasattr(node.slice, "value") and ok_node(node.slice.value):
            return node.slice.value
        else:
            assert (
                hasattr(node.slice, "lower")
                and hasattr(node.slice, "upper")
                and hasattr(node.slice, "step")
            )

            if ok_node(node.slice.step):
                return node.slice.step
            elif ok_node(node.slice.upper):
                return node.slice.upper
            else:
                return ok_node(node.slice.lower)

    elif isinstance(node, ast.Raise):
        if ok_node(node.cause):
            return node.cause
        elif ok_node(node.exc):
            return node.exc
    
    elif isinstance(node, (ast.For, ast.While, ast.If, ast.With)):
        return True  # There is last child, but I don't know which it will be
    
    # TODO: pick more cases from here:
    """
    (isinstance(node, (ast.IfExp, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
            # or isinstance(node, ast.FunctionDef, ast.Lambda) and len(node.args.defaults) > 0
                and (node.dest is not None or len(node.values) > 0))

            #"TODO: Import ja ImportFrom"
            # TODO: what about ClassDef ???
    """

    return None


def mark_text_ranges(node, source: bytes):
    """
    Node is an AST, source is corresponding source as string.
    Function adds recursively attributes end_lineno and end_col_offset to each node
    which has attributes lineno and col_offset.
    """
    try:
        from asttokens import ASTTokens
    except ImportError:
        # asttokens may be missing in some configurations
        from thonny.ast_utils_old_range_marker import old_mark_text_ranges
        logger = logging.getLogger("thonny")
        if not getattr(logger, "old_astutils_warned", False):
            logger.warn("asttokens not found, using deprecated alternative")
            logger.old_astutils_warned = True
        return old_mark_text_ranges(node, source)

    
    ASTTokens(source.decode('utf8'), tree=node)
    for child in ast.walk(node):
        if hasattr(child, 'last_token'):
            child.end_lineno, child.end_col_offset = child.last_token.end

            if hasattr(child, 'lineno'):
                # Fixes problems with some nodes like binop
                child.lineno, child.col_offset = child.first_token.start


def pretty(node, key="/", level=0):
    """Used for testing and new test generation via AstView.
    Don't change the format without updating tests"""
    if isinstance(node, ast.AST):
        fields = [(key, val) for key, val in ast.iter_fields(node)]
        value_label = node.__class__.__name__
        if isinstance(node, ast.Call):
            # Try to make 3.4 AST-s more similar to 3.5
            if sys.version_info[:2] == (3, 4):
                if ("kwargs", None) in fields:
                    fields.remove(("kwargs", None))
                if ("starargs", None) in fields:
                    fields.remove(("starargs", None))

            # TODO: translate also non-None kwargs and starargs

    elif isinstance(node, list):
        fields = list(enumerate(node))
        if len(node) == 0:
            value_label = "[]"
        else:
            value_label = "[...]"
    else:
        fields = []
        value_label = repr(node)

    item_text = level * "    " + str(key) + "=" + value_label

    if hasattr(node, "lineno"):
        item_text += " @ " + str(getattr(node, "lineno"))
        if hasattr(node, "col_offset"):
            item_text += "." + str(getattr(node, "col_offset"))

        if hasattr(node, "end_lineno"):
            item_text += "  -  " + str(getattr(node, "end_lineno"))
            if hasattr(node, "end_col_offset"):
                item_text += "." + str(getattr(node, "end_col_offset"))

    lines = [item_text] + [
        pretty(field_value, field_key, level + 1) for field_key, field_value in fields
    ]

    return "\n".join(lines)
