{% if create_stub_files %}
import React from "react";
import { useServer } from "./_server/useServer";

const Home = () => {
  const serverState = useServer();

  return (
    <div className="min-h-screen bg-gray-50 p-8">
      <div className="mx-auto max-w-3xl">
        <h1 className="mb-8 text-4xl font-light tracking-tight text-gray-900">Tasks</h1>
        
        <button
          className="mb-8 inline-flex items-center rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2"
          onClick={async () => {
            await serverState.new_detail({
              signal: undefined,
            });
          }}
        >
          <svg className="mr-2 h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
          </svg>
          New Task
        </button>

        <div className="space-y-4">
          {serverState.items.map((item) => (
            <div
              key={item.id}
              className="group relative rounded-lg border border-gray-200 bg-white p-6 shadow-sm"
            >
              <div className="mb-2 text-lg text-gray-800">{item.description}</div>
              <a
                className="inline-flex items-center text-sm font-medium text-indigo-600 transition-colors hover:text-indigo-800"
                href={serverState.linkGenerator.detailController({
                  detail_id: item.id!,
                })}
              >
                View Details
                <svg className="ml-1 h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </a>
            </div>
          ))}
          
          {serverState.items.length === 0 && (
            <div className="rounded-lg border-2 border-dashed border-gray-200 p-8 text-center">
              <p className="text-gray-500">No tasks yet. Create your first task to get started!</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default Home;
{% endif %}