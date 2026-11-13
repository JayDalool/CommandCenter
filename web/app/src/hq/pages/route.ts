// The address an HQ page stands for, and where its own navigation goes. In the main window both are the window's own
// (lib/router.ts). In a pop-out window (#/pop/<view>, hq/windows/PopWindow.tsx) the page stands for its own address,
// with no task, project or parameter, and opening something from it goes to the main window, as its links do. Pages
// read the address here, never with useRoute(): a pop-out's own address is #/pop/<view>, which parses as screen "pop".
import { createContext, useContext } from "react";
import { go, useRoute, type Route } from "../../lib/router";

export interface PageNav { route: Route; go: typeof go }

const Ctx = createContext<PageNav | null>(null);
export const PageNavProvider = Ctx.Provider;

export function usePageNav(): PageNav {
  const route = useRoute();
  return useContext(Ctx) ?? { route, go };
}
