# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['nervmap/__main__.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['nervmap.cli', 'nervmap.config', 'nervmap.models', 'nervmap.utils', 'nervmap.scanner', 'nervmap.discovery.docker', 'nervmap.discovery.systemd', 'nervmap.discovery.ports', 'nervmap.discovery.process', 'nervmap.topology.mapper', 'nervmap.topology.fingerprints', 'nervmap.diagnostics.engine', 'nervmap.diagnostics.rules', 'nervmap.diagnostics.rules.network', 'nervmap.diagnostics.rules.docker_rules', 'nervmap.diagnostics.rules.systemd_rules', 'nervmap.diagnostics.rules.dependencies', 'nervmap.diagnostics.rules.resources', 'nervmap.diagnostics.rules.code_rules', 'nervmap.output.console', 'nervmap.output.json_out', 'nervmap.output.hooks', 'nervmap.source', 'nervmap.source.locator', 'nervmap.source.linker', 'nervmap.source.cache', 'nervmap.source.models', 'nervmap.source.parsers', 'nervmap.source.parsers.python_parser', 'nervmap.source.parsers.js_parser', 'nervmap.source.parsers.config_parser', 'nervmap.ai', 'nervmap.ai.collector', 'nervmap.ai.chain_parser', 'nervmap.ai.config_resolver', 'nervmap.ai.console', 'nervmap.ai.models', 'nervmap.ai.rules', 'nervmap.ai.signatures', 'nervmap.web', 'nervmap.web.server', 'nervmap.web.security'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='nervmap-linux-amd64',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
