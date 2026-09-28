import { bindNavigationSearch } from "./retorna/navigation-search.js";
import { bindAppearance } from "./retorna/appearance.js";
import "../styles/retorna.scss";
import { bindGentelellaShell } from "./integrations/gentelella/shell.js";
import { bindSidebarSections } from "./retorna/sidebar-sections.js";
import { bindUserMenu } from "./retorna/user-menu.js";
import { bindIntegracaoForm } from "./retorna/integracao-form.js";
import { bindCampaignScope } from "./retorna/campaign-scope.js";
import { bindInviteShare } from "./retorna/invite-share.js";
import { bindComposedForms } from "./retorna/composed-form.js";

bindAppearance();
bindGentelellaShell();
bindSidebarSections();
bindUserMenu();
bindIntegracaoForm();
bindCampaignScope();
bindInviteShare();
bindComposedForms();

bindNavigationSearch();

import { bindConversaoResgate } from './retorna/conversao-resgate.js';
bindConversaoResgate();

import { bindStoreSearch } from "./retorna/store-search.js";
bindStoreSearch();
