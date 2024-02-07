import React from "react";
import { useServer } from "./_server/useServer";

const Home = () => {
  const serverState = useServer();

  return (
    <div className="p-6">
      <h1 className="text-2xl">Home</h1>
      <div>Current Count: {serverState.current_count}</div>
      <div><a
        className="font-medium text-blue-500"
        href={serverState.linkGenerator.detailController({
          detail_id: "9280ca4d-e607-486a-a343-7bbaae6b5a86",
        })}>View Details</a></div>
      <div className="flex gap-x-4">
        <button
          className="rounded-md bg-blue-500 p-2 text-white"
          onClick={async () => {
            await serverState.increment_count({
              requestBody: {
                count: 1,
              },
            });
          }}
        >
          Increment
        </button>
        <button
          className="rounded-md bg-blue-500 p-2 text-white"
          onClick={async () => {
            await serverState.increment_count({
              requestBody: {
                count: -1,
              },
            });
          }}
        >
          Decrement
        </button>
      </div>
    </div>
  );
};

export default Home;
