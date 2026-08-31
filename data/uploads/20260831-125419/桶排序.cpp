#include <bits/stdc++.h>
using namespace std;
int n;
int a[101],s,ma=0;
int main()
{
	cin>>n;
	for(int i=0;i<n;i++){
		cin>>s;
		ma=max(ma,s);
		a[s]++;
	}
	for(int i=ma;i>0;i--){
		if(a[i]!=0){
			for(int j=1;j<=a[i];j++)cout<<i<<ends;
		}
	}
	return 0;
}

