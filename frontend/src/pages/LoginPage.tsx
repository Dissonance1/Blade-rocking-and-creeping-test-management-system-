import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation } from "@tanstack/react-query";
import axios from "axios";
import { Eye, EyeOff, Loader2, AlertCircle } from "lucide-react";
import "@fontsource/inter/400.css";
import "@fontsource/inter/700.css";
import "@fontsource/montserrat/700.css";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";

import { useAuthStore } from "@/store/authStore";
import { authService } from "@/services/authService";
import { extractApiError } from "@/services/api";
import { getRoleHomePath } from "@/routes";
import { cn } from "@/utils/cn";

// ─── Validation schema ────────────────────────────────────────────────────────

const loginSchema = z.object({
  email: z.string().min(1, "Email/Username is required").email("Invalid email address"),
  password: z.string().min(1, "Password is required").min(8, "Password must be at least 8 characters"),
});

type LoginFormValues = z.infer<typeof loginSchema>;

// ─── Component ────────────────────────────────────────────────────────────────

export default function LoginPage() {
  const navigate = useNavigate();
  const setAuth = useAuthStore((s) => s.setAuth);
  const [showPassword, setShowPassword] = useState(false);
  const [emailFocused, setEmailFocused] = useState(false);
  const [passwordFocused, setPasswordFocused] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    mode: "onTouched",
    reValidateMode: "onChange",
    shouldFocusError: false,
  });

  const emailField = register("email");
  const passwordField = register("password");

  const emailHasError = Boolean(errors.email) && !emailFocused;
  const passwordHasError = Boolean(errors.password) && !passwordFocused;

  const loginMutation = useMutation({
    mutationFn: (values: LoginFormValues) => authService.login(values),
    onSuccess: ({ user, tokens }) => {
      setAuth(user, tokens);
      navigate(getRoleHomePath(user.roles), { replace: true });
    },
  });

  const loginErrorMessage =
    axios.isAxiosError(loginMutation.error) && loginMutation.error.response?.status === 401
      ? "Wrong credentials, try again."
      : extractApiError(loginMutation.error);

  const onSubmit = (values: LoginFormValues) => loginMutation.mutate(values);

  return (
    <div className="min-h-screen flex items-center justify-center bg-white">
      <div className="absolute top-6 right-6">
        <div className="flex items-center gap-4 rounded-xl border border-slate-300 bg-white px-4 py-3 shadow-md">
          <img src="/media/login/HAL.png" alt="HAL" className="h-[46px] w-auto object-contain" />
          <div className="h-12 w-px bg-slate-200" />
          <img src="/media/login/MDL.png" alt="Meridian Data Labs" className="h-[38px] w-auto object-contain" />
        </div>
      </div>

      <span className="absolute bottom-7 right-8 text-[13px] font-medium uppercase tracking-wide text-slate-400">
        Built by @ Meridian Data Labs
      </span>
      <div className="relative w-full max-w-md px-4">
        {/* Logo / Branding area */}
        <div className="flex flex-col items-center mb-6">
          <img
            src="/media/login/Light.png"
            alt="Blade Rocking & Creep Test System"
            className="h-16 w-16 object-contain mb-3"
          />
          <h1
            className="text-2xl font-bold text-slate-900 tracking-tight text-center leading-tight"
            style={{ fontFamily: "Montserrat, Verdana, Geneva, sans-serif" }}
          >
            Blade Rocking &amp; Creeping
          </h1>
          <p
            className="text-slate-600 text-sm mt-1.5 text-center"
            style={{ fontFamily: "Inter, Verdana, Geneva, sans-serif" }}
          >
            Advanced Test Management System
          </p>
        </div>

        <Card
          className="border-slate-200 shadow-xl rounded-2xl overflow-hidden bg-no-repeat bg-cover bg-center"
          style={{
            backgroundColor: "#ffffff",
            backgroundImage:
              "linear-gradient(rgba(255,255,255,0.85), rgba(255,255,255,0.85)), url(/media/login/BackgroundImageLight.png)",
          }}
        >
          <CardHeader className="pb-4">
            <CardTitle className="text-black text-xl">Sign In</CardTitle>
            <CardDescription className="text-slate-500">
              Enter your credentials to access the system
            </CardDescription>
          </CardHeader>

          <CardContent>
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
              {/* Global error */}
              {loginMutation.isError && (
                <Alert variant="destructive" className="border-red-500/50 bg-red-50">
                  <AlertCircle className="h-4 w-4 text-red-500" />
                  <AlertDescription className="text-red-700">
                    {loginErrorMessage}
                  </AlertDescription>
                </Alert>
              )}

              {/* Email */}
              <div className="space-y-1.5">
                <Label htmlFor="email" className="text-slate-600 text-sm font-medium">
                  Email/Username
                </Label>
                <div className="relative">
                  <Input
                    id="email"
                    type="email"
                    autoComplete="email"
                    spellCheck={false}
                    autoCapitalize="off"
                    autoCorrect="off"
                    placeholder="Email/Username"
                    className={cn(
                      "bg-white text-slate-900 placeholder:text-slate-400 h-11 focus-visible:ring-0 focus-visible:ring-offset-0",
                      emailHasError
                        ? "border-red-500 focus:border-red-500 pr-10"
                        : "border-slate-300 focus:border-slate-400"
                    )}
                    {...emailField}
                    onFocus={() => setEmailFocused(true)}
                    onBlur={(e) => {
                      emailField.onBlur(e);
                      setEmailFocused(false);
                    }}
                  />
                  {emailHasError && (
                    <AlertCircle className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-red-500" />
                  )}
                </div>
                {emailHasError && (
                  <p className="text-red-500 text-xs mt-1">{errors.email?.message}</p>
                )}
              </div>

              {/* Password */}
              <div className="space-y-1.5">
                <Label htmlFor="password" className="text-slate-600 text-sm font-medium">
                  Password
                </Label>
                <div className="relative">
                  <Input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    placeholder="Password"
                    className={cn(
                      "bg-white text-slate-900 placeholder:text-slate-400 h-11 focus-visible:ring-0 focus-visible:ring-offset-0",
                      passwordHasError
                        ? "border-red-500 focus:border-red-500 pr-16"
                        : "border-slate-300 focus:border-slate-400 pr-10"
                    )}
                    {...passwordField}
                    onFocus={() => setPasswordFocused(true)}
                    onBlur={(e) => {
                      passwordField.onBlur(e);
                      setPasswordFocused(false);
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-700 transition-colors"
                    tabIndex={-1}
                    aria-label={showPassword ? "Hide password" : "Show password"}
                  >
                    {showPassword ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}
                  </button>
                  {passwordHasError && (
                    <AlertCircle className="absolute right-9 top-1/2 -translate-y-1/2 w-4 h-4 text-red-500" />
                  )}
                </div>
                {passwordHasError && (
                  <p className="text-red-500 text-xs mt-1">{errors.password?.message}</p>
                )}
              </div>

              {/* Submit */}
              <Button
                type="submit"
                disabled={loginMutation.isPending}
                className="w-full h-11 bg-orange-500 hover:bg-orange-600 text-white font-semibold mt-1 transition-colors shadow-md shadow-orange-200"
              >
                {loginMutation.isPending ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Signing in…
                  </>
                ) : (
                  "Continue"
                )}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
