describe("Cart", () => {
  beforeEach(() => cy.visit("/"));

  it("counts added items", () => {
    cy.get("#add-to-cart").click();
    cy.get("#cart-count").should("have.text", "1");
  });

  it("confirms the item was added", () => {
    cy.get("#add-to-cart").click();
    // The confirmation waits on the warehouse stock check, whose latency varies.
    cy.get("#toast", { timeout: 3000 }).should("be.visible");
  });
});
