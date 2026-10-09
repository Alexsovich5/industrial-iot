"""Checks that README.md only names real files and shows the tracked tree."""

import os
import re
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
README_PATH = os.path.join(ROOT, 'README.md')

# A backticked token is treated as a repo path when it has no spaces or
# shell/URL characters and either contains a slash or ends in a file
# extension used in this repo.
PATH_TOKEN = re.compile(r'^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*/?$')
FILE_EXTENSIONS = (
    '.py', '.ino', '.h', '.cpp', '.ini', '.conf', '.json', '.yml', '.txt',
    '.md', '.cfg',
)
BANNED_TEXT = ('shields.io', 'Organization', 'Developed during')


def render_tree(paths):
    """Render sorted file paths as an indented tree, directories first seen
    in path order and suffixed with a slash, two spaces per level."""
    lines = []
    open_dirs = []
    for path in paths:
        parts = path.split('/')
        dirs, name = parts[:-1], parts[-1]
        common = 0
        while (common < len(open_dirs) and common < len(dirs)
               and open_dirs[common] == dirs[common]):
            common += 1
        for depth in range(common, len(dirs)):
            lines.append('  ' * depth + dirs[depth] + '/')
        open_dirs = dirs
        lines.append('  ' * len(dirs) + name)
    return '\n'.join(lines)


def tracked_files():
    output = subprocess.check_output(['git', 'ls-files'], cwd=ROOT)
    return sorted(output.decode('utf-8').splitlines())


@pytest.fixture(scope='module')
def readme():
    with open(README_PATH) as handle:
        return handle.read()


def backtick_paths(text):
    paths = []
    for token in re.findall(r'`([^`\n]+)`', text):
        if not PATH_TOKEN.match(token):
            continue
        if '/' in token or token.endswith(FILE_EXTENSIONS):
            paths.append(token)
    return paths


def layout_block(text):
    match = re.search(r'^## Layout\n\n```\n(.*?)\n```', text, re.M | re.S)
    assert match, 'README has no fenced Layout block'
    return match.group(1)


def test_render_tree_groups_files_under_directories():
    paths = ['Makefile', 'a/b/c.py', 'a/b/d.py', 'a/e.py', 'f.txt']
    assert render_tree(paths) == '\n'.join([
        'Makefile',
        'a/',
        '  b/',
        '    c.py',
        '    d.py',
        '  e.py',
        'f.txt',
    ])


def test_backtick_paths_ignores_commands_and_topics():
    text = ('Run `make test`, see `src/readings.py`, `README.md`, '
            '`socket://host:7000`, `paho-mqtt==1.3.0`, `/dev/ttyACM0`.')
    assert backtick_paths(text) == ['src/readings.py', 'README.md']


def test_readme_names_only_existing_paths(readme):
    paths = backtick_paths(readme)
    assert paths, 'expected README to reference repo files'
    missing = [p for p in paths if not os.path.exists(os.path.join(ROOT, p))]
    assert missing == []


def test_readme_has_no_badges_or_employer_text(readme):
    for text in BANNED_TEXT:
        assert text not in readme


def test_readme_has_no_template_leftovers(readme):
    assert '{{' not in readme
    assert '<!--' not in readme


def test_readme_states_hardware_is_simulated(readme):
    assert ('Arduino sensor nodes, the serial link and the Raspberry Pi '
            'gateway are simulated') in readme
    assert 'has not been flashed to a board in this repo' in readme


@pytest.mark.skipif(not os.path.isdir(os.path.join(ROOT, '.git')),
                    reason='git metadata is not available')
def test_layout_matches_tracked_files(readme):
    assert layout_block(readme) == render_tree(tracked_files())
