from .simple_classes_1 import SubClass1, SuperClass2


class SubClass2(SuperClass2):
    pass


class SubSubClass(SubClass1, SubClass2):
    pass


class UnrelatedClass:
    pass
