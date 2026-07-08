import React, { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import Footer from "@/layouts/components/Navbar/Footer";
import { useAuthStore } from "@/store/authStore";
import KTIcon from "@/components/common/KTIcon";
import { Check } from "lucide-react";
import { toast } from "sonner";

export default function MyProfile() {
  const { user } = useAuthStore();
  const [fullName, setFullName] = useState(user?.full_name || "");

  const handleSave = () => {
    toast.success("Profile updated successfully");
    // API call would go here
  };

  if (!user) return null;

  const initials = user.full_name
    ? user.full_name.split(" ").map(n => n[0]).join("").toUpperCase().slice(0, 2)
    : user.username.slice(0, 2).toUpperCase();

  const primaryRole = user.roles[0];
  const roleLabel = primaryRole ? primaryRole.replace("_", " ") : "USER";

  return (
    <div className="max-w-3xl mx-auto w-full h-full flex flex-col justify-center pb-12">
      <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 shadow-sm">
        <CardHeader className="pb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-orange-500 flex items-center justify-center text-white shrink-0 shadow-sm">
              <KTIcon iconName="user" className="text-xl leading-none" />
            </div>
            <div>
              <CardTitle className="text-xl text-slate-900 dark:text-white">Profile</CardTitle>
              <CardDescription className="text-sm mt-0.5 text-slate-500 dark:text-slate-400">
                Update your personal information
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        
        <div className="px-6">
          <hr className="border-slate-100 dark:border-slate-800" />
        </div>

        <CardContent className="pt-6 space-y-8">
          {/* User Info Section */}
          <div className="flex items-center gap-5">
            <div className="w-16 h-16 rounded-full bg-slate-200 dark:bg-slate-800 flex items-center justify-center shrink-0 shadow-sm overflow-hidden">
              <img src="/media/avatars/Avatar.png" alt="Avatar" className="w-full h-full object-cover scale-125" />
            </div>
            <div className="flex flex-col gap-1 min-w-0">
              <h2 className="text-lg font-semibold text-slate-900 dark:text-white truncate">
                {user.full_name || user.username}
              </h2>
              <p className="text-sm text-slate-500 dark:text-slate-400 truncate">
                {user.email}
              </p>
              <Badge className="bg-slate-900 text-white w-fit mt-1 hover:bg-slate-900 shadow-sm uppercase border-0">
                {roleLabel}
              </Badge>
            </div>
          </div>

          <div className="px-0">
            <hr className="border-slate-100 dark:border-slate-800" />
          </div>

          {/* Form Section */}
          <div className="space-y-5">
            <div className="space-y-2">
              <Label htmlFor="fullName" className="text-slate-600 dark:text-slate-300">Full Name</Label>
              <Input 
                id="fullName" 
                value={fullName} 
                onChange={(e) => setFullName(e.target.value)} 
                className="bg-white dark:bg-slate-950 border-slate-200 dark:border-slate-700"
              />
            </div>
            
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
              <div className="space-y-2">
                <Label htmlFor="email" className="text-slate-600 dark:text-slate-300">Email (read-only)</Label>
                <Input 
                  id="email" 
                  value={user.email} 
                  readOnly 
                  className="bg-slate-50 dark:bg-slate-900/50 text-slate-500 dark:text-slate-400 border-slate-200 dark:border-slate-700 cursor-not-allowed focus-visible:ring-0"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="username" className="text-slate-600 dark:text-slate-300">Username (read-only)</Label>
                <Input 
                  id="username" 
                  value={user.username} 
                  readOnly 
                  className="bg-slate-50 dark:bg-slate-900/50 text-slate-500 dark:text-slate-400 border-slate-200 dark:border-slate-700 cursor-not-allowed focus-visible:ring-0"
                />
              </div>
            </div>

            <div className="pt-2">
              <Button onClick={handleSave} className="bg-orange-500 hover:bg-orange-600 text-white shadow-sm border-0 font-medium">
                <Check className="w-4 h-4 mr-2" /> Save Profile
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="shrink-0 pb-3 pt-4">
        <Footer />
      </div>
    </div>
  );
}
