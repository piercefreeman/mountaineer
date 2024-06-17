import * as React from "react";
import { useServer } from "./_server";

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

  const counts: number[][] = [];

  if (serverState.delay_loops > 0) {
    // Arbitrarily do a lot of work to simulate a really complex page
    // Takes about 5 seconds
    for (let i = 0; i < serverState.delay_loops; i++) {
      counts.push(findPrimes(10000000));
    }
  }

  if (serverState.throw_client_error) {
    throw new Error("Example client error");
  }

  return (
    <div className="p-6">
      <h1 className="text-2xl">Server</h1>
      <p>Ran with delay: {serverState.delay_loops}</p>
      <p>
        Throw client error: {serverState.throw_client_error ? "true" : "false"}
      </p>
      <p>
        Delay Loop Calculations:{" "}
        <ul>
          {counts.map((count, i) => (
            <li key={i}>- {count.length}</li>
          ))}{" "}
        </ul>
        {serverState.random_uuid}
      </p>
      <p>
        <a
          className="font-medium text-blue-500"
          href={serverState.linkGenerator.complexController({
            detail_id: "9280ca4d-e607-486a-a343-7bbaae6b5a86",
            delay_loops: 4,
          })}
        >
          Test SSR Timeout (Wait ~5s)
        </a>
      </p>
      <p>
        <a
          className="font-medium text-blue-500"
          href={serverState.linkGenerator.complexController({
            detail_id: "9280ca4d-e607-486a-a343-7bbaae6b5a86",
            throw_client_error: true,
          })}
        >
          Test SSR Exception
        </a>
      </p>
      <p>
        <a
          className="font-medium text-blue-500"
          href={serverState.linkGenerator.homeController({})}
        >
          Go Home
        </a>
      </p>
    </div>
  );
};

export default Page;
