from ansiblereview import Result, Error, parse_inventory, get_vault_password
from ansible.errors import AnsibleError
import inspect
import os
import ansible.parsing.dataloader

_vars = dict()
_inv = None


def get_group_vars(group, inventory, invfile, vaultpass):
    try:
        from ansible.plugins.loader import vars_loader
        from ansible.utils.vars import combine_vars
        loader = ansible.parsing.dataloader.DataLoader()
        if vaultpass:
            if hasattr(loader, 'set_vault_secrets'):
                from ansible.module_utils._text import to_bytes
                from ansible.parsing.vault import VaultSecret
                loader.set_vault_secrets([('default', VaultSecret(_bytes=to_bytes(vaultpass)))])
            else:
                # not tested
                loader.set_vault_password(vaultpass)
        # variables in inventory file
        vars = group.get_vars()
        # variables in group_vars related to invfile
        for p in vars_loader.all():
            gvars = p.get_vars(loader, invfile, group)
            vars = combine_vars(vars, gvars)
        return vars
    except ImportError:
        pass
    # http://stackoverflow.com/a/197053
    vars = inspect.getargspec(inventory.get_group_vars)
    if 'return_results' in vars[0]:
        return inventory.get_group_vars(group, return_results=True)
    else:
        return inventory.get_group_vars(group)


def remove_inherited_and_overridden_vars(vars, group, inventory, invfile, vaultpass):
    if group not in _vars:
        _vars[group] = get_group_vars(group, inventory, invfile, vaultpass)
    gv = _vars[group]
    for (k, v) in vars.items():
        if k in gv:
            if gv[k] == v:
                vars.pop(k)
            else:
                gv.pop(k)


def remove_inherited_and_overridden_group_vars(group, inventory, invfile, vaultpass):
    if group not in _vars:
        _vars[group] = get_group_vars(group, inventory, invfile, vaultpass)
    for ancestor in group.get_ancestors():
        remove_inherited_and_overridden_vars(_vars[group], ancestor, inventory, invfile, vaultpass)


def same_variable_defined_in_competing_groups(candidate, options):
    result = Result(candidate.path)

    vaultpass = get_vault_password(options)
    # assume that group_vars file is under an inventory *directory*
    sdirs = candidate.path.split(os.sep)
    if sdirs.index('group_vars') == 0:
        invfile = os.getcwd()
    else:
        invfile = os.path.join(*sdirs[:sdirs.index('group_vars')])
    grpname = os.path.splitext(sdirs[sdirs.index('group_vars')+1])[0]
    global _inv

    try:
        inv = _inv or parse_inventory(invfile)
    except AnsibleError as e:
        result.errors = [Error(None, "Inventory is broken: %s" % e.message)]
        return result

    if hasattr(inv, 'groups'):
        group = inv.groups.get(grpname)
    else:
        group = inv.get_group(grpname)
    if not group:
        # group file exists in group_vars but no related group
        # in inventory directory
        return result
    remove_inherited_and_overridden_group_vars(group, inv, invfile, vaultpass)
    group_vars = set(_vars[group].keys())
    child_hosts = group.hosts
    child_groups = group.child_groups
    siblings = set()

    for child_host in child_hosts:
        siblings.update(child_host.groups)
    for child_group in child_groups:
        siblings.update(child_group.parent_groups)
    for sibling in siblings:
        if sibling != group:
            remove_inherited_and_overridden_group_vars(sibling, inv, invfile, vaultpass)
            sibling_vars = set(_vars[sibling].keys())
            common_vars = sibling_vars & group_vars
            common_hosts = [host.name for host in set(child_hosts) & set(sibling.hosts)]
            if common_vars and common_hosts:
                for var in common_vars:
                    error_msg_template = "Sibling groups {0} and {1} with common hosts {2} " + \
                                         "both define variable {3}"
                    error_msg = error_msg_template.format(group.name, sibling.name,
                                                          ", ".join(common_hosts), var)
                    result.errors.append(Error(None, error_msg))

    return result
