#include <bits/stdc++.h>
using namespace std;
string s1,s2;
int a[100005],b[100005],c[100005];
int p; 
int main()
{
	cin>>s1>>s2;
	int lena=s1.size(),lenb=s2.size(),lenc=lena+lenb;
	for(int i=0;i<lena;i++){
		a[lena-i-1]=s1[i]-'0';
	}
	for(int i=0;i<lenb;i++){
		b[lenb-i-1]=s2[i]-'0';
	}
	for(int i=0;i<lena;i++){
		for(int j=0;j<lenb;j++){
			c[i+1]+=a[i]*b[j];
			c[i+j+1]+=c[i+j+1]+c[i+j]/10;
			c[i+j]%=10; 
		}
	}
	while(c[lenc]==0&&lenc!=0)lenc--;
	for(int i=lenc;i>=0;i--)cout<<c[i];
}
