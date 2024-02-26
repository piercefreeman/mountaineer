{% if create_stub_files %}
import React from "react";
import { useServer } from "./_server/useServer";

const Home = () => {
  const serverState = useServer();

  return (
    <div className="p-6">
      <h1 className="text-2xl">Home</h1>
      <button
        className="rounded-md bg-blue-500 p-2 text-white"
        onClick={async () => {
          await serverState.new_detail({
            requestBody: {
            },
          });
        }}
      >New Item</button>
      <div>
        {
          serverState.items.map(
            (item) => (
              <div key={item.id} className="p-2">
                <div>{item.description}</div>
                <a
                  className="font-medium text-blue-500"
                  href={serverState.linkGenerator.detailController({
                    detail_id: item.id,
                  })}>View Details</a>
              </div>
            )
          )
        }
      </div>
    </div>
  );
};

export default Home;
{% endif %}