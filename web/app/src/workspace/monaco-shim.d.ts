declare module "monaco-editor/editor/editor.main" {
  export * from "monaco-editor";
}
declare module "*?worker" {
  const W: { new (): Worker };
  export default W;
}
