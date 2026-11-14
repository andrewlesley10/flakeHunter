const { defineConfig } = require("cypress");

module.exports = defineConfig({
  reporter: "mocha-junit-reporter",
  reporterOptions: {
    mochaFile: "reports/cypress-[hash].xml",
    testsuitesTitle: "cypress",
  },
  e2e: {
    baseUrl: "http://localhost:8000",
    supportFile: false,
    video: false,
    screenshotOnRunFailure: false,
  },
});
