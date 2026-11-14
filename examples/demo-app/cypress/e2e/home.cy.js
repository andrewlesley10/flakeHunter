describe("Home page", () => {
  it("lists every item", () => {
    cy.visit("/");
    cy.get("#items li").should("have.length", 3);
  });
});
