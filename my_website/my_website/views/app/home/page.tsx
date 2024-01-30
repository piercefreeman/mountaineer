import React from "react";
import { useServer } from "./_server/useServer";

const Home = () => {
  const serverState = useServer();
  console.log("SERVER PAYLOAD", serverState);

  return (
    <div>
      <h1>Home</h1>
      <p>Home page</p>
      <p>
        Hello {serverState.first_name}, current count is{" "}
        {serverState.current_count}
      </p>
      <button
        onClick={async () => {
          await serverState.increment_count({
            requestBody: {
              count: 1,
            },
          });
        }}
      >
        Increment V1
      </button>
      <button
        onClick={async () => {
          await serverState.increment_count_only({
            url_param: 5,
            requestBody: {
              count: 1,
            },
          });
        }}
      >
        Increment V2
      </button>
    </div>
  );
};

export default Home;
