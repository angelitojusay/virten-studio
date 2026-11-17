import sys
from lupa import LuaRuntime
lua = LuaRuntime()
check = lua.eval("function(s, n) local f, e = load(s, '=' .. n); if f then return 'OK' else return 'SYNTAX ERROR: ' .. e end end")
for f in sys.argv[1:]:
    print(f.split("\\")[-1], check(open(f, encoding="utf-8").read(), f.split("\\")[-1]))
