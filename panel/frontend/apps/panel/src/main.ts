import { createApp } from "vue";
import { createPinia } from "pinia";
import { createRouter, createWebHistory } from "vue-router";
const NotificationsPage = () => import("./pages/NotificationsPage.vue");
const CustomerNotificationsPage = () => import("./pages/CustomerNotificationsPage.vue");
const SupportPage = () => import("./pages/SupportPage.vue");
const CustomerSupportPage = () => import("./pages/CustomerSupportPage.vue");
const RolesPage = () => import("./pages/RolesPage.vue");
const StaffPage = () => import("./pages/StaffPage.vue");
const SettingsPage = () => import("./pages/SettingsPage.vue");
const HostGroupsPage = () => import("./pages/HostGroupsPage.vue");
const NodeCoresPage = () => import("./pages/NodeCoresPage.vue");
const CustomerServicePage = () => import("./pages/CustomerServicePage.vue");
import App from "./App.vue";
const LoginPage = () => import("./pages/LoginPage.vue");
const DashboardPage = () => import("./pages/DashboardPage.vue");
const CustomersPage = () => import("./pages/CustomersPage.vue");
const LoyaltyPage = () => import("./pages/LoyaltyPage.vue");
const PlansPage = () => import("./pages/PlansPage.vue");
const PaymentsPage = () => import("./pages/PaymentsPage.vue");
const SubscriptionsPage = () => import("./pages/SubscriptionsPage.vue");
const ConfigurationsPage = () => import("./pages/ConfigurationsPage.vue");
const NetworkPage = () => import("./pages/NetworkPage.vue");
const TestToolsPage = () => import("./pages/TestToolsPage.vue");
const AutomationPage = () => import("./pages/AutomationPage.vue");
const WalletPage = () => import("./pages/WalletPage.vue");
const CustomerAccountPage = () => import("./pages/CustomerAccountPage.vue");
const CustomerSignInPage = () => import("./pages/CustomerSignInPage.vue");
import { useCustomerAuth } from "@papilio/auth";
import { useAuth, useResellerAuth } from "@papilio/auth";
const ResellerCustomersPage = () => import("./pages/ResellerCustomersPage.vue");
const ResellerSubscriptionsPage = () => import("./pages/ResellerSubscriptionsPage.vue");
const ResellerPlansPage = () => import("./pages/ResellerPlansPage.vue");
const ResellersPage = () => import("./pages/ResellersPage.vue");
const ResellerTeamPage = () => import("./pages/ResellerTeamPage.vue");
const ResellerLoginPage = () => import("./pages/ResellerLoginPage.vue");
const ResellerProfilePage = () => import("./pages/ResellerProfilePage.vue");
import "./style.css";
import "@papilio/ui/display.css";
import { i18n } from "./i18n";
import { setApiErrorTranslator } from "@papilio/api";

setApiErrorTranslator(code => {
  const key = `errors.${code}`;
  return i18n.global.te(key) ? i18n.global.t(key) : undefined;
});

const pinia = createPinia();
const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/reseller/customers", meta: { reseller: true, scope: "customers" }, component: ResellerCustomersPage },
    { path: "/reseller/subscriptions", meta: { reseller: true, scope: "subscriptions" }, component: ResellerSubscriptionsPage },
    { path: "/reseller/customers/:customerId/subscriptions", meta: { reseller: true, scope: "subscriptions" }, component: ResellerSubscriptionsPage },
    { path: "/resellers/:resellerId/plans", meta: { scope: "resellers" }, component: ResellerPlansPage },
    { path: "/reseller/plans", meta: { reseller: true, scope: "catalog" }, component: ResellerPlansPage },
    { path: "/resellers", meta: { scope: "resellers" }, component: ResellersPage },
    { path: "/resellers/:resellerId/team", meta: { scope: "resellers" }, component: ResellerTeamPage },
    { path: "/reseller/login", meta: { reseller: true }, component: ResellerLoginPage },
    { path: "/reseller", meta: { reseller: true }, component: ResellerProfilePage },
    { path: "/reseller/team", meta: { reseller: true, scope: "team" }, component: ResellerTeamPage },
    { path: "/account/sign-in", meta: { public: true, customer: true }, component: CustomerSignInPage },
    { path: "/account/notifications", meta: { customer: true }, component: CustomerNotificationsPage },
    { path: "/account/support", meta: { customer: true }, component: CustomerSupportPage },
    { path: "/account", meta: { customer: true }, component: CustomerAccountPage },
    { path: "/service/:token", meta: { public: true }, component: CustomerServicePage },
    { path: "/login", component: LoginPage },
    { path: "/", component: DashboardPage },
    { path: "/customers", meta: { scope: "customers" }, component: CustomersPage },
    { path: "/customers/:customerId/wallet", meta: { scope: "payments" }, component: WalletPage },
    { path: "/automation", meta: { scopes: ["payments", "network", "subscriptions"] }, component: AutomationPage },
    { path: "/loyalty", meta: { scope: "catalog" }, component: LoyaltyPage },
    { path: "/plans", meta: { scope: "catalog" }, component: PlansPage },
    { path: "/payments", meta: { scope: "payments" }, component: PaymentsPage },
    { path: "/subscriptions", meta: { scope: "subscriptions" }, component: SubscriptionsPage },
    { path: "/notifications", meta: { scope: "notifications" }, component: NotificationsPage },
    { path: "/support", meta: { scope: "support" }, component: SupportPage },
    { path: "/roles", meta: { scope: "staff" }, component: RolesPage },
    { path: "/staff", meta: { scope: "staff" }, component: StaffPage },
    { path: "/settings", meta: { scope: "settings" }, component: SettingsPage },
    { path: "/host-groups", meta: { scope: "network" }, component: HostGroupsPage },
    { path: "/network/:nodeId/cores", meta: { scope: "network" }, component: NodeCoresPage },
    { path: "/network/:nodeId/cores/:coreId/configurations", meta: { scope: "network" }, component: ConfigurationsPage },
    { path: "/network", meta: { scope: "network" }, component: NetworkPage },
    { path: "/connection-lab", meta: { scope: "network" }, component: TestToolsPage },
    { path: "/configurations", meta: { scope: "network" }, component: ConfigurationsPage },
    { path: "/network/:nodeId/configurations", meta: { scope: "network" }, component: ConfigurationsPage },
  ],
});
router.beforeEach(async to => {
  if (to.meta.public) return true;
  if (to.meta.reseller) {
    const reseller=useResellerAuth(pinia);
    if(!reseller.checked) await reseller.restore();
    if(!reseller.session) return to.path === "/reseller/login" ? true : "/reseller/login";
    if(to.path === "/reseller/login") return "/reseller";
    if(typeof to.meta.scope === "string" && !reseller.can(to.meta.scope)) return "/reseller";
    return true;
  }
  if (to.meta.customer) { const customer=useCustomerAuth(pinia); if(!customer.checked) await customer.restore(); return customer.session ? true : "/account/sign-in"; }
  const auth = useAuth(pinia);
  if (!auth.checked) await auth.restore();
  if (!auth.session && to.path !== "/login") return "/login";
  if (auth.session && to.path === "/login") return "/";
  if (auth.session && typeof to.meta.scope === "string" && !auth.can(to.meta.scope)) return "/";
  if (auth.session && Array.isArray(to.meta.scopes) && !to.meta.scopes.some(scope => typeof scope === "string" && auth.can(scope))) return "/";
  return true;
});
createApp(App).use(pinia).use(i18n).use(router).mount("#app");
