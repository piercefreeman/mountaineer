import * as React from "react";
import { useEffect } from "react";
import { useServer } from "./_server/useServer";

const WrapperLayout = ({ children }: { children: React.ReactNode }) => {
  return (
    <div>
      <h1>{{ project_name }}</h1>
      <div>{children}</div>
    </div>
  );
};

export default WrapperLayout;
