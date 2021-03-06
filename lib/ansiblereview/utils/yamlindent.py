#!/usr/bin/env python

"""
Quick and dirty YAML checker.
Verifies that lines only increase indentation by 2
and that lines starting '- ' don't have additional
indentation.
Blank lines are ignored.

GOOD:

```
- tasks:
  - name: hello world
    command: echo hello

  - name: another task
    debug:
      msg: hello
```

BAD:

```
- tasks:
   # comment in random indentation
    - name: hello world
      debug:
          msg: hello
```
"""


from __future__ import print_function
import os
import codecs
import re
import sys
from ansiblereview import Result, Error, utils, get_decrypted_file, get_vault_password, classify


def indent_checker(filename):
    with codecs.open(filename, mode='rb', encoding='utf-8') as f:
        indent_regex = re.compile(r"^(?P<indent>\s*(?:- )?)(?P<rest>.*)$")
        verb_regex = re.compile(".*: [|>]\d?$")
        lineno = 0
        prev_indent = ''
        verbatim = False
        errors = []
        for line in f:
            lineno += 1
            match = indent_regex.match(line)
            if verb_regex.match(line):
                verbatim = True
            if len(match.group('rest')) == 0:
                if verbatim:
                    verbatim = False
                continue
            if verbatim:
                continue
            curr_indent = match.group('indent')
            offset = len(curr_indent) - len(prev_indent)
            if offset > 0 and offset != 2:
                if match.group('indent').endswith('- '):
                    errors.append(Error(lineno, "lines starting with '- ' should have same "
                                  "or less indentation than previous line"))
                else:
                    errors.append(Error(lineno, "indentation should increase by 2 chars"))
            prev_indent = curr_indent
        return errors


def yamlreview(candidate, settings):
    vaultpass = get_vault_password(settings)
    fname = get_decrypted_file(candidate.path, vaultpass)
    errors = indent_checker(fname)
    if candidate.path not in fname:
        os.unlink(fname)
    return Result(candidate.path, errors)


if __name__ == '__main__':
    args = sys.argv[1:] or [sys.stdin]
    rc = 0
    for arg in args:
        options = utils.Settings({})
        result = yamlreview(classify(arg, options), options)
        for error in result.errors:
            print("ERROR: %s:%s: %s" % (arg, error.lineno, error.message), file=sys.stderr)
            rc = 1
    sys.exit(rc)
