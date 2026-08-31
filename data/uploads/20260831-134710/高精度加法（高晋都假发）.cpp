#include <bits/stdc++.h>
using namespace std;
string s1,s2;
int a[100005],b[100005],c[100005];
int main()
{
	cin>>s1>>s2;
	int lena=s1.size(),lenb=s2.size(),lenc;
	for(int i=0;i<lena;i++){
		a[lena-i-1]=s1[i]-'0';
	}
	for(int i=0;i<lenb;i++){
		b[lenb-i-1]=s2[i]-'0';
	}
	lenc=max(lena,lenb);
	for(int i=0;i<lenc;i++){
		c[i]+=a[i]+b[i];
		c[i+1]+=c[i]/10;
		c[i]%=10;
	}
	if(c[lenc+1]!=0)lenc++;
	while(c[lenc]==0&&lenc>0)lenc--;
	for(int i=lenc;i>=0;i--){
		cout<<c[i];
	}
	return 0;
}
