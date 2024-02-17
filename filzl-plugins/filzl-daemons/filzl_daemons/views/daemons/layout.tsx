import React, { ReactNode } from "react";

const Layout = ({ children }: { children: ReactNode }) => {
  return (
    <div className="h-auto min-h-screen w-full bg-white">
      <div className="mx-auto max-w-3xl pt-4">
        <div className="border-b-4 border-blue-400 text-4xl font-medium">
          Admin / Daemons
        </div>
        <div className="mt-8">{children}</div>
      </div>
    </div>
  );
};

export default Layout;
