const app = require("./app.json").expo;

module.exports = {
  ...app,
  android: {
    ...app.android,
    usesCleartextTraffic: process.env.NODE_ENV !== "production",
  },
};
