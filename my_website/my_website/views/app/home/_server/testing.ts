interface IComplete {
  a: string;
  b: string;
  c: (x: string) => number;
  d: (x: number) => string;
}

// helper function
const asPartialIComplete = <T extends Partial<IComplete>>(t: T) => t;

const part1 = asPartialIComplete({
  a: "hello",
  c: (x) => x.length,
});

const part2 = asPartialIComplete({
  b: "world",
  d: (x) => x + "",
});

const together: IComplete = {
  ...part1,
  ...part2,
};
