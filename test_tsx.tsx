import React from "react";

const Main = () => {
  const serverValues = useServer();
  const otherValue = 5;

  return (
    <html>
      {serverValues.testing1}
      {serverValues.testing2.othervalue}
      {otherValue}
    </html>
  );
};

export default Main;
