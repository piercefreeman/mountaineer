class Main:
    def __call__(self, *args, **kwargs):
        pass

def testing():
    def embedded_fn():
        item2 = Main()
        item2(whee2=True)

    item = Main()
    item(whee=True)

    print("TEST")
