#include <bits/stdc++.h>
using namespace std;
int n;
int main()
{
	cin>>n;
	int n1=(n/10)%10;
	int n2=(n/100)%10;
	if(n1%2==1||n2%2==1)cout<<"Yes";
	else cout<<"No";
    return 0;
}
