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
