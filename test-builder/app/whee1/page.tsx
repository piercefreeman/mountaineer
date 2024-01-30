import { useState, useEffect } from "react";
import { v4 as uuidv4 } from "uuid";

const Page = () => {
  const [id, setID] = useState("");
  useEffect(() => {
    setID(uuidv4());
  }, []);

  return <div>Page 1: {id}</div>;
};

export default Page;
