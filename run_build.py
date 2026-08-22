import builtins, sys
it = iter(['y', 'n'])
builtins.input = lambda _: next(it)
sys.argv=['_fullbuild.py']
exec(open('_fullbuild.py').read(), {'__file__': '_fullbuild.py', '__name__': '__main__'})
