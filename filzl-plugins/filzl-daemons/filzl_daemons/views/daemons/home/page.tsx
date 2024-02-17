import React from "react";
import { useServer } from "./_server/useServer";

const Home = () => {
  const serverState = useServer();

  return (
    <div>
      <div className="mt-4 rounded border border-gray-300 shadow">
        <div className="flex">
          <div className="divide-y divide-gray-200 border-r border-gray-200">
            {serverState.stats.map((stat) => {
              return (
                <div key={stat.workflow_name} className="p-4">
                  <div className="font-medium">{stat.workflow_name}</div>
                </div>
              );
            })}
          </div>
          <div className="divide-y divide-gray-200 overflow-x-auto">
            {serverState.stats.map((stat) => {
              return (
                <div
                  key={stat.workflow_name}
                  className="flex whitespace-nowrap p-4 text-blue-500"
                >
                  {"█ ".repeat(stat.count * 2000)}
                </div>
              );
            })}
          </div>
        </div>
      </div>
      <div className="mt-4 text-2xl">Instances</div>
      <div className="mt-8 flow-root">
        <div className="-mx-4 -my-2 overflow-x-auto sm:-mx-6 lg:-mx-8">
          <div className="inline-block min-w-full py-2 align-middle sm:px-6 lg:px-8">
            <table className="min-w-full divide-y divide-gray-300">
              <thead>
                <tr>
                  <th
                    scope="col"
                    className="py-3.5 pl-4 pr-3 text-left text-sm font-semibold text-gray-900 sm:pl-0"
                  >
                    Workflow
                  </th>
                  <th
                    scope="col"
                    className="px-3 py-3.5 text-left text-sm font-semibold text-gray-900"
                  >
                    Status
                  </th>
                  <th
                    scope="col"
                    className="px-3 py-3.5 text-left text-sm font-semibold text-gray-900"
                  >
                    Launch Name
                  </th>
                  <th scope="col" className="relative py-3.5 pl-3 pr-4 sm:pr-0">
                    <span className="sr-only">Detail</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {serverState.instances.map((instance) => (
                  <tr key={instance.id}>
                    <td className="whitespace-nowrap py-4 pl-4 pr-3 text-sm font-medium text-gray-900 sm:pl-0">
                      {instance.workflow_name}
                    </td>
                    <td className="whitespace-nowrap px-3 py-4 text-sm text-gray-500">
                      <span className="inline-flex items-center rounded-md bg-green-50 px-2 py-1 text-xs font-medium text-green-700 ring-1 ring-inset ring-green-600/20">
                        {instance.status}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-3 py-4 text-sm text-gray-500">
                      {instance.launch_time}
                    </td>
                    <td className="relative whitespace-nowrap py-4 pl-3 pr-4 text-right text-sm font-medium sm:pr-0">
                      <a
                        href={serverState.linkGenerator.daemonDetailController({
                          instance_id: instance.id,
                        })}
                        className="text-indigo-600 hover:text-indigo-900"
                      >
                        View
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Home;
