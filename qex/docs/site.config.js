export default {
  name: "qex",
  description: "Semantic code search MCP server",
  navLinks: [
    { label: "Docs", href: "#getting-started" },
    { label: "Architecture", href: "#architecture" },
    { label: "MCP Tools", href: "#mcp-tools" },
    { label: "GitHub", href: "https://github.com/us/qex", external: true },
  ],
  sidebar: [
    {
      title: "Getting Started",
      children: [
        { title: "Introduction", slug: "getting-started" },
        { title: "Installation", slug: "installation" },
      ],
    },
    {
      title: "Core Concepts",
      children: [
        { title: "Architecture", slug: "architecture" },
        { title: "Search Pipeline", slug: "search-pipeline" },
        { title: "Indexing", slug: "indexing" },
        { title: "Languages", slug: "languages" },
      ],
    },
    {
      title: "Reference",
      children: [
        { title: "MCP Tools", slug: "mcp-tools" },
        { title: "Configuration", slug: "configuration" },
        { title: "Performance", slug: "performance" },
      ],
    },
  ],
  defaultPage: "getting-started",
  footer: {
    left: "Released under the MIT License",
    right: "Built with Rust",
  },
};
