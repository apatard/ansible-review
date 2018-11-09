import codecs
import os
import yaml
from yaml.composer import Composer
from ansiblereview import Result, Error, get_vault_password, get_decrypted_file


def hunt_repeated_yaml_keys(data):
    """Parses yaml and returns a list of repeated variables and
       the line on which they occur
    """
    loader = yaml.Loader(data)

    def compose_node(parent, index):
        # the line number where the previous token has ended (plus empty lines)
        line = loader.line
        node = Composer.compose_node(loader, parent, index)
        node.__line__ = line + 1
        return node

    def construct_mapping(node, deep=False):
        mapping = dict()
        errors = dict()
        for key_node, value_node in node.value:
            key = key_node.value
            if key in mapping:
                if key in errors:
                    errors[key].append(key_node.__line__)
                else:
                    errors[key] = [mapping[key], key_node.__line__]

            mapping[key] = key_node.__line__

        return errors

    loader.compose_node = compose_node
    loader.construct_mapping = construct_mapping
    data = loader.get_single_data()
    return data


def repeated_vars(candidate, settings):
    vaultpass = get_vault_password(settings)
    fname = get_decrypted_file(candidate.path, vaultpass)
    with codecs.open(fname, 'r') as f:
        errors = hunt_repeated_yaml_keys(f) or dict()
    if candidate.path not in fname:
        os.unlink(fname)
    return Result(candidate, [Error(err_line, "Variable %s occurs more than once" % err_key)
                              for err_key in errors for err_line in errors[err_key]])
