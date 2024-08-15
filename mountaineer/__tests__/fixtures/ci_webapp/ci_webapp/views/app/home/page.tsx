import React from "react";
import { useServer, HTTPValidationErrorException } from "./_server";
import { CustomComponent } from "./element";

const Home = () => {
  const serverState = useServer();
  console.log("SERVER PAYLOAD", serverState);

  return (
    <div className="p-6">
      <h1 className="text-2xl">Home</h1>
      <p className="text-green-500">Home page</p>
      <p>
        Hello {serverState.client_ip}, current count is{" "}
        {serverState.current_count} {serverState.random_uuid}
      </p>
      <CustomComponent />
      <p>
        <a
          className="font-medium text-blue-500"
          href={serverState.linkGenerator.detailController({
            detail_id: "9280ca4d-e607-486a-a343-7bbaae6b5a86",
          })}
        >
          Detail Link
        </a>
      </p>
      <p>
        <a
          className="font-medium text-blue-500"
          href={serverState.linkGenerator.complexController({
            detail_id: "9280ca4d-e607-486a-a343-7bbaae6b5a86",
          })}
        >
          Test Complex Link
        </a>
      </p>
      <p>
        <a
          className="font-medium text-blue-500"
          href={serverState.linkGenerator.streamController({})}
        >
          Stream Link
        </a>
      </p>
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
            try {
              await serverState.increment_count({
                requestBody: {
                  // @ts-ignore - we want this payload to be invalid
                  count: "invalid payload",
                },
              });
            } catch (error) {
              if (error instanceof HTTPValidationErrorException) {
                console.log(
                  "Validation Error",
                  error.body.detail?.[0].loc,
                  error.body.detail?.[0].msg,
                );
              } else {
                throw error;
              }
            }
          }}
        >
          Invalid Increment
        </button>
        <button
          className="rounded-md bg-blue-500 p-2 text-white"
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
    </div>
  );
};

export default Home;
