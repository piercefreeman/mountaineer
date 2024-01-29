import React from "react";
import { useServer } from "./_server/useServer";

const Home = () => {
  const serverState = useServer();

  return (
    <div>
      <h1>Home</h1>
      <p>Home page</p>
      <p>Hello {serverState.first_name}</p>
    </div>
  );
};

export default Home;
