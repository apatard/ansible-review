from ansiblelint import default_rulesdir, RulesCollection
import codecs
import subprocess
from functools import partial
import re
import os
from ansiblereview import utils
try:
    import ansible.parsing.dataloader
    from ansible.vars.manager import VariableManager
    from ansible.module_utils._text import to_bytes
    from ansible.parsing.vault import VaultSecret
    ANSIBLE = 2
except ImportError:
    try:
        from ansible.vars.manager import VariableManager
        ANSIBLE = 2
    except ImportError:
        ANSIBLE = 1

try:
    # Ansible 2.4 import of module loader
    from ansible.plugins.loader import module_loader
except ImportError:
    try:
        from ansible.plugins import module_loader
    except ImportError:
        from ansible.utils import module_finder as module_loader


class AnsibleReviewFormatter(object):

    def format(self, match):
        formatstr = u"{0}:{1}: [{2}] {3} {4}"
        return formatstr.format(match.filename,
                                match.linenumber,
                                match.rule.id,
                                match.message,
                                match.line
                                )


class Standard(object):
    def __init__(self, standard_dict):
        self.name = standard_dict.get("name")
        self.version = standard_dict.get("version")
        self.check = standard_dict.get("check")
        self.types = standard_dict.get("types")

    def __repr__(self):
        return "Standard: %s (version: %s, types: %s)" % (
               self.name, self.version, self.types)


class Error(object):
    def __init__(self, lineno, message):
        self.lineno = lineno
        self.message = message

    def __repr__(self):
        if self.lineno:
            return "%s: %s" % (self.lineno, self.message)
        else:
            return self.message


class Result(object):
    def __init__(self, candidate, errors=None):
        self.candidate = candidate
        self.errors = errors or []

    def message(self):
        return "\n".join(["{0}:{1}".format(self.candidate, error)
                          for error in self.errors])


class Candidate(object):
    def __init__(self, filename):
        self.path = filename
        self.realpath = filename
        try:
            self.version = find_version(filename)
            self.binary = False
        except UnicodeDecodeError:
            self.binary = True
        self.filetype = type(self).__name__.lower()
        self.expected_version = True

    def review(self, settings, lines=None):
        return utils.review(self, settings, lines)

    def __repr__(self):
        return "%s (%s)" % (type(self).__name__, self.path)

    def __getitem__(self, item):
        return self.__dict__.get(item)


class RoleFile(Candidate):
    def __init__(self, filename):
        super(RoleFile, self).__init__(filename)
        self.version = None
        parentdir = os.path.dirname(os.path.abspath(filename))
        while parentdir != os.path.dirname(parentdir):
            meta_file = os.path.join(parentdir, "meta", "main.yml")
            if os.path.exists(meta_file):
                self.version = find_version(meta_file)
                if self.version:
                    break
            parentdir = os.path.dirname(parentdir)
        role_modules = os.path.join(parentdir, 'library')
        if os.path.exists(role_modules):
            module_loader.add_directory(role_modules)


class Playbook(Candidate):
    pass


class Task(RoleFile):
    def __init__(self, filename):
        super(Task, self).__init__(filename)
        self.filetype = 'tasks'


class Handler(RoleFile):
    def __init__(self, filename):
        super(Handler, self).__init__(filename)
        self.filetype = 'handlers'


class Vars(Candidate):
    pass


class Unversioned(Candidate):
    def __init__(self, filename):
        super(Unversioned, self).__init__(filename)
        self.expected_version = False


class InventoryVars(Unversioned):
    def __init__(self, filename, options):
        super(InventoryVars, self).__init__(filename)
        pwd = get_vault_password(options)
        self.realpath = get_decrypted_file(filename, pwd)
        self.encrypted = False
        if filename not in self.realpath:
            self.encrypted = True
            self.version = find_version(self.realpath)

    def __del__(self):
        if self.encrypted:
            os.unlink(self.realpath)

    pass


class HostVars(InventoryVars):
    pass


class GroupVars(InventoryVars):
    pass


class RoleVars(RoleFile):
    pass


class Meta(RoleFile):
    pass


class Inventory(Unversioned):
    pass


class Code(Unversioned):
    pass


class Template(RoleFile):
    pass


class Doc(Unversioned):
    pass


# For ease of checking files for tabs
class Makefile(Unversioned):
    pass


class File(RoleFile):
    pass


class Rolesfile(Unversioned):
    pass


def classify(filename, options):
    parentdir = os.path.basename(os.path.dirname(filename))
    if parentdir in ['tasks']:
        return Task(filename)
    if parentdir in ['handlers']:
        return Handler(filename)
    if parentdir in ['vars', 'defaults']:
        return RoleVars(filename)
    if 'group_vars' in os.path.dirname(filename).split(os.sep):
        return GroupVars(filename, options)
    if 'host_vars' in os.path.dirname(filename).split(os.sep):
        return HostVars(filename, options)
    if parentdir == 'meta':
        return Meta(filename)
    if parentdir in ['library', 'lookup_plugins', 'callback_plugins',
                     'filter_plugins'] or filename.endswith('.py'):
        return Code(filename)
    if parentdir in ['inventory']:
        return Inventory(filename)
    if 'rolesfile' in filename or 'requirements' in filename:
        return Rolesfile(filename)
    if 'Makefile' in filename:
        return Makefile(filename)
    if 'templates' in filename.split(os.sep) or filename.endswith('.j2'):
        return Template(filename)
    if 'files' in filename.split(os.sep):
        return File(filename)
    if filename.endswith('.yml') or filename.endswith('.yaml'):
        return Playbook(filename)
    if 'README' in filename:
        return Doc(filename)
    return None


def lintcheck(rulename):
    return partial(ansiblelint, rulename)


def ansiblelint(rulename, candidate, settings):
    result = Result(candidate.path)
    rules = RulesCollection()
    rules.extend(RulesCollection.create_from_directory(default_rulesdir))
    if settings.lintdir:
        rules.extend(RulesCollection.create_from_directory(settings.lintdir))

    fileinfo = dict(path=candidate.path, type=candidate.filetype)
    matches = rules.run(fileinfo, rulename.split(','))
    result.errors = [Error(match.linenumber, "[%s] %s" % (match.rule.id, match.message))
                     for match in matches]
    return result


def find_version(filename, version_regex=r"^# Standards: ([0-9]+\.[0-9]+)"):
    version_re = re.compile(version_regex)
    with codecs.open(filename, mode='rb', encoding='utf-8') as f:
        for line in f:
            match = version_re.match(line)
            if match:
                return match.group(1)
    return None


def parse_inventory(fname):
    inv = {}

    # ansible throws warnings when parsing files in the inventory directory
    # when a plugin cant parse a file. This may be tweaked by [inventory]
    # configuration but not sure relying on that is a good idea.
    # So, if the inventory is a directory, try to find "known" files.
    invfile = fname
    if os.path.isdir(invfile):
        for hfile in ['hosts', 'hosts.yml', 'hosts.yaml', 'inventory']:
            hfile = os.path.join(invfile, hfile)
            if os.path.exists(hfile):
                invfile = hfile
                break
    if ANSIBLE > 1:
        loader = ansible.parsing.dataloader.DataLoader()
        try:
            from ansible.inventory.manager import InventoryManager
            inv = InventoryManager(loader=loader, sources=invfile)
        except ImportError:
            var_manager = VariableManager()
            inv = ansible.inventory.Inventory(loader=loader,
                                              variable_manager=var_manager,
                                              host_list=invfile)
    else:
        inv = ansible.inventory.Inventory(invfile)
    return inv


def get_vault_password(options):
    # is there a better way of doing this ?
    # doesnt handle multiple vault ids.
    pwd = None
    if hasattr(options, 'vaultpass') and options.vaultpass:
        if os.path.isfile(options.vaultpass):
            if os.access(options.vaultpass, os.X_OK):
                pwd = subprocess.check_output([os.path.abspath(options.vaultpass)])
            else:
                with open(options.vaultpass) as f:
                    pwd = f.read()
            pwd = pwd.strip()
        else:
            pwd = options.vaultpass
    return pwd


def get_decrypted_file(fname, vaultpass=None):
    if ANSIBLE > 1:
        loader = ansible.parsing.dataloader.DataLoader()
        if vaultpass:
            if hasattr(loader, 'set_vault_secrets'):
                loader.set_vault_secrets([('default', VaultSecret(_bytes=to_bytes(vaultpass)))])
            else:
                # not tested
                loader.set_vault_password(vaultpass)
        return loader.get_real_file(fname)
    else:
        return fname
