import os

from weft import cli


def test_plugin_path_prints_existing_dir(capsys):
    assert cli.main(["usdview-plugin-path"]) == 0
    d = capsys.readouterr().out.strip()
    assert os.path.isabs(d)
    assert os.path.isfile(os.path.join(d, "plugInfo.json"))
    assert os.path.isfile(os.path.join(d, "weftViewer", "__init__.py"))
