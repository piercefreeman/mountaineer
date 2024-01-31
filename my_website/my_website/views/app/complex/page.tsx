import * as React from "react";
import { useServer } from "./_server/useServer";

function isPrime(num: number) {
  if (num <= 1) return false;
  if (num === 2) return true;

  const limit = Math.sqrt(num);
  for (let divisor = 2; divisor <= limit; divisor++) {
    if (num % divisor === 0) {
      return false;
    }
  }

  return true;
}

function findPrimes(end = 5000) {
  const primes: number[] = [];
  for (let current = 2; current <= end; current++) {
    if (isPrime(current)) {
      primes.push(current);
    }
  }
  return primes;
}

const Page = () => {
  const serverState = useServer();

  // Arbitrarily do a lot of work to simulate a really complex page
  // Takes about 5 seconds
  const count = findPrimes(10000000);

  return (
    <div>
      <h1>Server</h1>
      <p>
        Count: {count[0]} {count[count.length - 1]} {serverState.random_uuid}
      </p>
    </div>
  );
};

export default Page;
