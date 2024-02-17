import React, { ReactNode } from "react";

const Layout = ({ children }: { children: ReactNode }) => {
  return (
    <div className="mx-auto mt-4 max-w-3xl bg-white">
      <div className="border-b-4 border-gray-400 text-4xl font-medium">
        Admin / Daemons
      </div>
      <div className="mt-8">{children}</div>
    </div>
  );
};

export default Layout;
