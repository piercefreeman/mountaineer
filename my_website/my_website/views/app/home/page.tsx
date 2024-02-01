import React from "react";
import { useServer } from "./_server/useServer";

const Home = () => {
  const serverState = useServer();
  console.log("SERVER PAYLOAD", serverState);

  return (
    <div>
      <h1>Home</h1>
      <p className="text-green-500">Home page</p>
      <p>
        Hello {serverState.client_ip}, current count is{" "}
        {serverState.current_count} {serverState.random_uuid}
      </p>
      <a
        href={serverState.linkGenerator.detailController({
          detail_id: "9280ca4d-e607-486a-a343-7bbaae6b5a86",
        })}
      >
        Detail Link
      </a>
      <button
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
        onClick={async () => {
          await serverState.increment_count_only({
            // Not used, but demonstrates that it's possible to pass a url param
            url_param: 5,
            requestBody: {
              count: -1,
            },
          });
        }}
      >
        Decrement with sideeffect masking
      </button>
    </div>
  );
};

export default Home;
