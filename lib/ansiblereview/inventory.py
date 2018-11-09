from ansiblereview import Result, Error, parse_inventory
import codecs
import yaml


def no_vars_in_host_file(candidate, options):
    errors = []
    with codecs.open(candidate.path, mode='rb', encoding='utf-8') as f:
        try:
            yaml.safe_load(f)
        except Exception:
            for (lineno, line) in enumerate(f):
                if ':vars]' in line:
                    errors.append(Error(lineno + 1, "contains a vars definition"))
    return Result(candidate.path, errors)


def parse(candidate, options):
    result = Result(candidate.path)
    try:
        parse_inventory(candidate.path)
    except Exception as e:
        result.errors = [Error(None, "Inventory is broken: %s" % e.message)]
    return result
