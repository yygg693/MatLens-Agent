import re, os, sys
os.chdir(r'D:\MatLens\design\prototype\js')
exports = {}
for f in os.listdir('.'):
    if not f.endswith('.js'): continue
    src = open(f, encoding='utf-8').read()
    names = set(re.findall(r'export\s+(?:function|const|let|var|class)\s+(\w+)', src))
    m = re.findall(r'export\s*\{([^}]+)\}', src)
    for n in m:
        names |= {x.strip() for x in n.split(',') if x.strip()}
    if names:
        exports[f] = names

main = open('main.js', encoding='utf-8').read()
imports = re.findall(r'import\s*\{([^}]+)\}\s*from\s*["\'](\./\w+\.js)["\']', main)
missing = []
for names, mod in imports:
    modfile = mod.lstrip('./')
    avail = exports.get(modfile, set())
    for n in names.split(','):
        n = n.strip()
        if n and n not in avail:
            missing.append(f'{n} <- {modfile} (not exported)')

# Also check window.* references in main.js that should be functions
if missing:
    print('MISSING:')
    for m in missing: print(' -', m)
else:
    print('ALL MAIN.JS IMPORTS OK')

# Cross-module: check each module's internal imports too
for f in os.listdir('.'):
    if not f.endswith('.js') or f == 'main.js': continue
    src = open(f, encoding='utf-8').read()
    imps = re.findall(r'import\s*\{([^}]+)\}\s*from\s*["\'](\./\w+\.js)["\']', src)
    for names, mod in imps:
        modfile = mod.lstrip('./')
        avail = exports.get(modfile, set())
        for n in names.split(','):
            n = n.strip()
            if n and n not in avail:
                print(f' - {f}: {n} <- {modfile} (not exported)')
